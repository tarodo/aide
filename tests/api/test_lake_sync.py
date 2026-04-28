from __future__ import annotations

import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.main import app
from backend.models.dataset import Dataset, DatasetHive
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.models.field import Field
from backend.models.field_binding import FieldBinding
from backend.models.field_link import FieldLink
from backend.models.system import System
from backend.models.system_flavor import SystemFlavor
from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)
from backend.models.type_instance import TypeInstance
from backend.models.user import User
from backend.scripts._seed_cast_rules_core import (
    seed_from_file as seed_casts_from_file,
)
from backend.scripts._seed_core import seed_from_file as seed_dt_from_file


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email=f"lake_sync_super_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
        is_superuser=True,
    )
    transactional_session.add(user)
    await transactional_session.commit()
    return user


@pytest_asyncio.fixture
async def headers(async_client: AsyncClient, superuser: User) -> dict[str, str]:
    r = await async_client.post(
        "/api/v1/login/",
        data={"username": superuser.email, "password": "password123"},
    )
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------- helpers (kept inline per CLAUDE.md guidance) ----------------


async def _seed_pg_and_iceberg(session: AsyncSession) -> None:
    await seed_dt_from_file(session, Path("backend/scripts/data/postgres14.yaml"))
    await seed_dt_from_file(session, Path("backend/scripts/data/iceberg_v2.yaml"))
    await seed_casts_from_file(
        session, Path("backend/scripts/data/casts_pg14_to_iceberg_v2.yaml")
    )


async def _create_pg_system(session: AsyncSession) -> System:
    flavor = (
        (
            await session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "postgres14")
            )
        )
        .scalars()
        .first()
    )
    sys = System(
        code=f"pg-src-{uuid.uuid4().hex[:6]}",
        name="PG Source",
        flavor_id=flavor.id,
    )
    session.add(sys)
    await session.flush()
    return sys


async def _create_lake_system(session: AsyncSession) -> System:
    flavor = (
        (
            await session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "iceberg_v2")
            )
        )
        .scalars()
        .first()
    )
    sys = System(
        code=f"lake-{uuid.uuid4().hex[:6]}",
        name="Lake",
        flavor_id=flavor.id,
    )
    session.add(sys)
    await session.flush()
    return sys


async def _make_source_dataset(
    session: AsyncSession, system: System
) -> tuple[Dataset, DatasetSchema, list[Field]]:
    """Create a minimal pg14 source: id bigint, amount numeric(10,2), tags array<int>."""
    from backend.models.dataset import DatasetRdbms

    ds = DatasetRdbms(
        kind="rdbms",
        system_id=system.id,
        object_name="public.users",
        schema_name="public",
        table_name="users",
        layer="raw",
    )
    session.add(ds)
    await session.flush()

    schema = DatasetSchema(dataset_id=ds.id, version_num=1)
    session.add(schema)
    await session.flush()

    pg_flavor = (
        (
            await session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "postgres14")
            )
        )
        .scalars()
        .first()
    )
    from backend.models.data_type import DataType

    pg_types = {
        dt.code: dt
        for dt in (
            await session.execute(
                select(DataType).where(DataType.system_flavor_id == pg_flavor.id)
            )
        ).scalars()
    }

    fields: list[Field] = []
    for idx, (name, dt_code, params, slot_children) in enumerate(
        [
            ("id", "bigint", {}, []),
            ("amount", "numeric", {"precision": 10, "scale": 2}, []),
            ("tags", "array", {}, [("item", "integer", {})]),
        ]
    ):
        fld = Field(dataset_id=ds.id, name=name, origin="mapped")
        session.add(fld)
        await session.flush()
        fields.append(fld)

        root_ti = TypeInstance(
            data_type_id=pg_types[dt_code].id,
            type_params=params or None,
            slot=None,
        )
        session.add(root_ti)
        await session.flush()
        for slot, child_code, child_params in slot_children:
            child_ti = TypeInstance(
                data_type_id=pg_types[child_code].id,
                type_params=child_params or None,
                slot=slot,
                parent_id=root_ti.id,
            )
            session.add(child_ti)
            await session.flush()

        binding = FieldBinding(
            field_id=fld.id,
            dataset_schema_id=schema.id,
            position=idx,
            is_nullable=(name != "id"),
            type_instance_id=root_ti.id,
        )
        session.add(binding)
        await session.flush()

    return ds, schema, fields


# ---------------- tests ----------------


@pytest.mark.asyncio
async def test_lake_sync_happy_path(
    async_client: AsyncClient,
    headers: dict,
    transactional_session: AsyncSession,
) -> None:
    await _seed_pg_and_iceberg(transactional_session)
    src_system = await _create_pg_system(transactional_session)
    lake_system = await _create_lake_system(transactional_session)
    ds, schema, _ = await _make_source_dataset(transactional_session, src_system)

    resp = await async_client.post(
        f"/api/v1/datasets/{ds.id}/lake-sync",
        headers=headers,
        json={
            "target_system_id": str(lake_system.id),
            "target_layer": "core",
            "db_name": "lake",
            "table_name": "users",
            "catalog_uri": "thrift://hms:9083",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mapped_field_count"] == 3
    assert body["tech_field_count"] == 0

    # Target DatasetHive exists.
    target_id = uuid.UUID(body["target_dataset_id"])
    hive = await transactional_session.get(DatasetHive, target_id)
    assert hive is not None
    assert hive.db_name == "lake"
    assert hive.table_name == "users"
    assert hive.file_format == "iceberg"

    # Schema v1 exists with 3 bindings.
    target_schema_id = uuid.UUID(body["target_dataset_schema_id"])
    bindings = (
        (
            await transactional_session.execute(
                select(FieldBinding).where(
                    FieldBinding.dataset_schema_id == target_schema_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(bindings) == 3

    # DatasetLink pinned to source latest schema and target schema.
    link_id = uuid.UUID(body["dataset_link_id"])
    link = await transactional_session.get(DatasetLink, link_id)
    assert link.source_schema_id == schema.id
    assert link.target_schema_id == target_schema_id

    # FieldLink count == mapped field count.
    flinks = (
        (
            await transactional_session.execute(
                select(FieldLink).where(FieldLink.dataset_link_id == link_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(flinks) == 3


@pytest.mark.asyncio
async def test_lake_sync_target_flavor_mismatch(
    async_client: AsyncClient,
    headers: dict,
    transactional_session: AsyncSession,
) -> None:
    await _seed_pg_and_iceberg(transactional_session)
    src_system = await _create_pg_system(transactional_session)
    # Wrong target — use the source system as target.
    ds, _, _ = await _make_source_dataset(transactional_session, src_system)

    resp = await async_client.post(
        f"/api/v1/datasets/{ds.id}/lake-sync",
        headers=headers,
        json={
            "target_system_id": str(src_system.id),
            "target_layer": "core",
            "db_name": "lake",
            "table_name": "users",
            "catalog_uri": "thrift://hms:9083",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "LAKE_SYNC_TARGET_FLAVOR_MISMATCH"


@pytest.mark.asyncio
async def test_lake_sync_existing_target_returns_409(
    async_client: AsyncClient,
    headers: dict,
    transactional_session: AsyncSession,
) -> None:
    await _seed_pg_and_iceberg(transactional_session)
    src_system = await _create_pg_system(transactional_session)
    lake_system = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, src_system)

    body = {
        "target_system_id": str(lake_system.id),
        "target_layer": "core",
        "db_name": "lake",
        "table_name": "users",
        "catalog_uri": "thrift://hms:9083",
    }
    first = await async_client.post(
        f"/api/v1/datasets/{ds.id}/lake-sync", headers=headers, json=body
    )
    assert first.status_code == 201

    second = await async_client.post(
        f"/api/v1/datasets/{ds.id}/lake-sync", headers=headers, json=body
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "DATASET_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_lake_sync_unknown_override_field(
    async_client: AsyncClient,
    headers: dict,
    transactional_session: AsyncSession,
) -> None:
    await _seed_pg_and_iceberg(transactional_session)
    src_system = await _create_pg_system(transactional_session)
    lake_system = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, src_system)

    resp = await async_client.post(
        f"/api/v1/datasets/{ds.id}/lake-sync",
        headers=headers,
        json={
            "target_system_id": str(lake_system.id),
            "target_layer": "core",
            "db_name": "lake",
            "table_name": "users",
            "catalog_uri": "thrift://hms:9083",
            "overrides": {"NOPE": {"data_type_code": "string"}},
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "LAKE_SYNC_UNKNOWN_OVERRIDE_FIELD"


@pytest.mark.asyncio
async def test_lake_sync_with_tech_template(
    async_client: AsyncClient,
    headers: dict,
    transactional_session: AsyncSession,
) -> None:
    await _seed_pg_and_iceberg(transactional_session)
    src_system = await _create_pg_system(transactional_session)
    lake_system = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, src_system)

    # Build a minimal tech template inline (no API).
    tpl = TechFieldTemplate(
        code=f"scd2_test_{uuid.uuid4().hex[:6]}",
        name="SCD2 test",
        layer="core",
    )
    transactional_session.add(tpl)
    await transactional_session.flush()
    for order, (name, type_code) in enumerate(
        [("valid_from", "TIMESTAMP"), ("is_current", "BOOLEAN")]
    ):
        transactional_session.add(
            TechFieldTemplateField(
                template_id=tpl.id, name=name, type_code=type_code, order=order
            )
        )
    await transactional_session.flush()

    resp = await async_client.post(
        f"/api/v1/datasets/{ds.id}/lake-sync",
        headers=headers,
        json={
            "target_system_id": str(lake_system.id),
            "target_layer": "core",
            "db_name": "lake",
            "table_name": "users",
            "catalog_uri": "thrift://hms:9083",
            "tech_template_id": str(tpl.id),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mapped_field_count"] == 3
    assert body["tech_field_count"] == 2

    target_id = uuid.UUID(body["target_dataset_id"])
    target_fields = (
        (
            await transactional_session.execute(
                select(Field).where(Field.dataset_id == target_id)
            )
        )
        .scalars()
        .all()
    )
    origins = sorted([f.origin for f in target_fields])
    # 3 mapped + 2 tech.
    assert origins == ["mapped", "mapped", "mapped", "tech", "tech"]


@pytest.mark.asyncio
async def test_lake_sync_override_unknown_data_type(
    async_client: AsyncClient, headers: dict, transactional_session: AsyncSession
) -> None:
    await _seed_pg_and_iceberg(transactional_session)
    src_system = await _create_pg_system(transactional_session)
    lake_system = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, src_system)

    resp = await async_client.post(
        f"/api/v1/datasets/{ds.id}/lake-sync",
        headers=headers,
        json={
            "target_system_id": str(lake_system.id),
            "target_layer": "core",
            "db_name": "lake",
            "table_name": "users",
            "catalog_uri": "thrift://hms:9083",
            "overrides": {"id": {"data_type_code": "nonexistent_iceberg_type"}},
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "DATA_TYPE_NOT_FOUND"


@pytest.mark.asyncio
async def test_lake_sync_ambiguous_cast_returns_candidates(
    async_client: AsyncClient, headers: dict, transactional_session: AsyncSession
) -> None:
    """When >1 cast rules exist for a source DT, response carries candidates."""
    from backend.models.cast_rule import CastRule
    from backend.models.data_type import DataType

    await _seed_pg_and_iceberg(transactional_session)
    src_system = await _create_pg_system(transactional_session)
    lake_system = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, src_system)

    # Inject a second cast rule for pg14.bigint → iceberg_v2.string,
    # alongside the seeded pg14.bigint → iceberg_v2.long.
    pg_flavor = (
        (
            await transactional_session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "postgres14")
            )
        )
        .scalars()
        .first()
    )
    ice_flavor = (
        (
            await transactional_session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "iceberg_v2")
            )
        )
        .scalars()
        .first()
    )

    pg_bigint = (
        (
            await transactional_session.execute(
                select(DataType).where(
                    DataType.system_flavor_id == pg_flavor.id,
                    DataType.code == "bigint",
                )
            )
        )
        .scalars()
        .first()
    )
    ice_string = (
        (
            await transactional_session.execute(
                select(DataType).where(
                    DataType.system_flavor_id == ice_flavor.id,
                    DataType.code == "string",
                )
            )
        )
        .scalars()
        .first()
    )

    transactional_session.add(
        CastRule(
            source_data_type_id=pg_bigint.id,
            target_data_type_id=ice_string.id,
            param_mapping={},
            safety="unsafe",
        )
    )
    await transactional_session.flush()

    resp = await async_client.post(
        f"/api/v1/datasets/{ds.id}/lake-sync",
        headers=headers,
        json={
            "target_system_id": str(lake_system.id),
            "target_layer": "core",
            "db_name": "lake",
            "table_name": "users",
            "catalog_uri": "thrift://hms:9083",
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error_code"] == "LAKE_SYNC_AMBIGUOUS_CAST"
    assert "details" in body
    assert body["details"]["field"] == "id"
    # Order is rule-discovery order; both candidates must appear.
    assert set(body["details"]["candidates"]) == {"long", "string"}
