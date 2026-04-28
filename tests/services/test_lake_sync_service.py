from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aide_schemas.lake_sync import LakeSyncRequest
from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_schema import DatasetSchema
from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)
from backend.services.lake_sync import LakeSyncService

# Re-use API-test helpers via direct import (kept inline per CLAUDE.md guidance —
# promote to tests/_helpers.py if a 3rd copy is needed).
from tests.api.test_lake_sync import (
    _create_lake_system,
    _create_pg_system,
    _make_source_dataset,
    _seed_pg_and_iceberg,
)


def _uow_for(session: AsyncSession) -> UnitOfWork:
    uow = UnitOfWork()
    uow.session_factory = lambda: session
    return uow


def _request(target_system_id: uuid.UUID, **overrides):
    base = {
        "target_system_id": target_system_id,
        "target_layer": "core",
        "db_name": "lake",
        "table_name": "users",
        "catalog_uri": "thrift://hms:9083",
    }
    base.update(overrides)
    return LakeSyncRequest(**base)


@pytest.mark.asyncio
async def test_source_dataset_not_found(transactional_session: AsyncSession):
    await _seed_pg_and_iceberg(transactional_session)
    lake = await _create_lake_system(transactional_session)
    service = LakeSyncService()

    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=uuid.uuid4(),
            request=_request(lake.id),
            applier_id=None,
        )
    assert exc.value.error_code == errors.DATASET_NOT_FOUND


@pytest.mark.asyncio
async def test_no_source_schema_with_bindings(
    transactional_session: AsyncSession,
):
    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    lake = await _create_lake_system(transactional_session)
    # Build dataset with schema but no FieldBindings.
    ds = DatasetRdbms(
        kind="rdbms",
        system_id=pg.id,
        object_name="empty",
        schema_name="public",
        table_name="empty",
    )
    transactional_session.add(ds)
    await transactional_session.flush()
    schema = DatasetSchema(dataset_id=ds.id, version_num=1)
    transactional_session.add(schema)
    await transactional_session.flush()

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(lake.id),
            applier_id=None,
        )
    assert exc.value.error_code == errors.LAKE_SYNC_NO_SOURCE_SCHEMA


@pytest.mark.asyncio
async def test_target_system_not_found(transactional_session: AsyncSession):
    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, pg)

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(uuid.uuid4()),  # bogus target system id
            applier_id=None,
        )
    assert exc.value.error_code == errors.SYSTEM_NOT_FOUND


@pytest.mark.asyncio
async def test_tech_template_not_found(transactional_session: AsyncSession):
    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    lake = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, pg)

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(lake.id, tech_template_id=uuid.uuid4()),
            applier_id=None,
        )
    assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_NOT_FOUND


@pytest.mark.asyncio
async def test_tech_template_layer_mismatch(transactional_session: AsyncSession):
    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    lake = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, pg)

    tpl = TechFieldTemplate(
        code=f"raw_only_{uuid.uuid4().hex[:6]}",
        name="raw layer template",
        layer="raw",  # request asks for `core`
    )
    transactional_session.add(tpl)
    await transactional_session.flush()

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(lake.id, tech_template_id=tpl.id),
            applier_id=None,
        )
    assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_LAYER_MISMATCH


@pytest.mark.asyncio
async def test_tech_type_code_not_resolvable(transactional_session: AsyncSession):
    """Tech template field with an unknown type_code → TECH_TYPE_CODE_NOT_RESOLVABLE."""
    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    lake = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, pg)

    tpl = TechFieldTemplate(
        code=f"bad_{uuid.uuid4().hex[:6]}",
        name="bad tech",
        layer="core",
    )
    transactional_session.add(tpl)
    await transactional_session.flush()
    transactional_session.add(
        TechFieldTemplateField(
            template_id=tpl.id,
            name="bogus",
            type_code="DEFINITELY_NOT_A_REAL_TYPE",
            order=0,
        )
    )
    await transactional_session.flush()

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(lake.id, tech_template_id=tpl.id),
            applier_id=None,
        )
    assert exc.value.error_code == errors.TECH_TYPE_CODE_NOT_RESOLVABLE


@pytest.mark.asyncio
async def test_soft_deleted_source_dataset_rejected(
    transactional_session: AsyncSession,
):
    from datetime import datetime, timezone

    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    lake = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, pg)

    # Naive datetime — asyncpg rejects aware datetimes for TIMESTAMP WITHOUT TZ.
    ds.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await transactional_session.flush()

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(lake.id),
            applier_id=None,
        )
    assert exc.value.error_code == errors.DATASET_NOT_FOUND
