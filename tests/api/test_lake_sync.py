from __future__ import annotations

import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.main import app
from backend.models.dataset import DatasetHive
from backend.models.dataset_link import DatasetLink
from backend.models.field import Field
from backend.models.field_binding import FieldBinding
from backend.models.field_link import FieldLink
from backend.models.system_flavor import SystemFlavor
from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)
from backend.models.user import User
from tests._helpers import (
    _create_lake_system,
    _create_pg_system,
    _make_source_dataset,
    _seed_pg_and_iceberg,
)


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
