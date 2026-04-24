import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
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
