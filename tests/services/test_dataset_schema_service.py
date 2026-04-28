import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.schemas.dataset_schema import DatasetSchemaCreate, DatasetSchemaUpdate
from backend.services.dataset_schema import DatasetSchemaService


@pytest.mark.asyncio
async def test_delete_pinned_schema_raises_in_use(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="DSS_K", name="DSS Kind")
    flavor = SystemFlavor(code="DSS_F", name="DSS Flavor", kind=kind)
    system = System(code="DSS_S", name="DSS System", flavor=flavor)
    src = DatasetRdbms(
        system=system,
        object_name="dss_src",
        kind="rdbms",
        schema_name="s",
        table_name="src",
    )
    tgt = DatasetRdbms(
        system=system,
        object_name="dss_tgt",
        kind="rdbms",
        schema_name="s",
        table_name="tgt",
    )
    transactional_session.add_all([kind, flavor, system, src, tgt])
    await transactional_session.flush()
    ss = DatasetSchema(dataset=src, version_num=1, schema={})
    ts = DatasetSchema(dataset=tgt, version_num=1, schema={})
    transactional_session.add_all([ss, ts])
    await transactional_session.flush()
    link = DatasetLink(
        source_dataset_id=src.id,
        target_dataset_id=tgt.id,
        source_schema_id=ss.id,
        target_schema_id=ts.id,
    )
    transactional_session.add(link)
    await transactional_session.flush()

    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session
    service = DatasetSchemaService()
    with pytest.raises(AppException) as exc:
        await service.delete(uow=uow, obj_id=ss.id, deleter_id=None)
    assert exc.value.error_code == errors.DATASET_SCHEMA_IN_USE


async def _seed_dataset_schema(session: AsyncSession, suffix: str):
    kind = SystemKind(code=f"DS_{suffix}", name=f"DS {suffix}")
    flavor = SystemFlavor(code=f"FL_{suffix}", name=f"Flavor {suffix}", kind=kind)
    sys_obj = System(code=f"SYS_{suffix}", name=f"Sys {suffix}", flavor=flavor)
    session.add_all([kind, flavor, sys_obj])
    await session.flush()
    ds = DatasetRdbms(
        kind="rdbms",
        system_id=sys_obj.id,
        object_name=f"o_{suffix}",
        schema_name="public",
        table_name=f"t_{suffix}",
    )
    session.add(ds)
    await session.flush()
    schema = DatasetSchema(dataset_id=ds.id, version_num=1, schema={})
    session.add(schema)
    await session.flush()
    return ds, schema


@pytest.mark.asyncio
async def test_delete_blocked_when_pinned_by_dataset_link(
    transactional_session: AsyncSession,
):
    src_ds, src_schema = await _seed_dataset_schema(transactional_session, "PIN1")
    tgt_ds, tgt_schema = await _seed_dataset_schema(transactional_session, "PIN2")
    link = DatasetLink(
        source_dataset_id=src_ds.id,
        target_dataset_id=tgt_ds.id,
        source_schema_id=src_schema.id,
        target_schema_id=tgt_schema.id,
    )
    transactional_session.add(link)
    await transactional_session.flush()

    service = DatasetSchemaService()
    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session

    with pytest.raises(AppException) as exc:
        await service.delete(uow=uow, obj_id=src_schema.id)
    assert exc.value.error_code == errors.DATASET_SCHEMA_IN_USE


@pytest.mark.asyncio
async def test_delete_allowed_when_no_active_link(
    transactional_session: AsyncSession,
):
    _, schema = await _seed_dataset_schema(transactional_session, "FREE")
    service = DatasetSchemaService()
    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session

    out = await service.delete(uow=uow, obj_id=schema.id)
    assert out.id == schema.id


@pytest.mark.asyncio
async def test_delete_not_found_raises(transactional_session: AsyncSession):
    service = DatasetSchemaService()
    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session

    with pytest.raises(AppException) as exc:
        await service.delete(uow=uow, obj_id=uuid.uuid4())
    assert exc.value.error_code == errors.DATASET_SCHEMA_NOT_FOUND


@pytest.mark.asyncio
async def test_create_renames_schema_underscore_to_schema(
    transactional_session: AsyncSession,
):
    """Pydantic alias `schema_` (avoiding BaseModel.schema clash) maps to model col `schema`."""
    ds, _ = await _seed_dataset_schema(transactional_session, "SCH")
    service = DatasetSchemaService()
    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session

    payload = DatasetSchemaCreate.model_validate(
        {
            "dataset_id": ds.id,
            "version_num": 2,
            "schema": {"columns": [{"name": "id"}]},
        }
    )
    created = await service.create(uow=uow, obj_in=payload)

    db_obj = await transactional_session.get(DatasetSchema, created.id)
    assert db_obj is not None
    assert db_obj.schema == {"columns": [{"name": "id"}]}


@pytest.mark.xfail(
    reason=(
        "DatasetSchemaService.update renames schema_ -> schema in a local dict "
        "but then delegates to super().update(obj_in=...) which re-dumps obj_in "
        "from scratch — the rename is dead code. Bug in "
        "backend/services/dataset_schema.py:109-113."
    ),
    strict=True,
)
@pytest.mark.asyncio
async def test_update_renames_schema_underscore_to_schema(
    transactional_session: AsyncSession,
):
    _, schema = await _seed_dataset_schema(transactional_session, "UPD")
    service = DatasetSchemaService()
    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session

    payload = DatasetSchemaUpdate.model_validate(
        {
            "schema": {"columns": [{"name": "ts"}]},
            "row_version": schema.row_version,
        }
    )
    schema_id = schema.id
    await service.update(uow=uow, obj_id=schema_id, obj_in=payload)

    db_obj = await transactional_session.get(DatasetSchema, schema_id)
    assert db_obj is not None
    assert db_obj.schema == {"columns": [{"name": "ts"}]}
