import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_schema import DatasetSchema
from backend.repositories.dataset_schema import DatasetSchemaRepository


async def _make_dataset(session: AsyncSession, name: str) -> DatasetRdbms:
    kind = SystemKind(code=f"K_{name}", name=f"K {name}")
    flavor = SystemFlavor(code=f"F_{name}", name=f"F {name}", kind=kind)
    system = System(code=f"S_{name}", name=f"S {name}", flavor=flavor)
    ds = DatasetRdbms(
        system=system, object_name=name, kind="rdbms",
        schema_name="s", table_name=name,
    )
    session.add_all([kind, flavor, system, ds])
    await session.flush()
    return ds


@pytest.mark.asyncio
async def test_latest_for_dataset_returns_highest_version(
    transactional_session: AsyncSession,
):
    ds = await _make_dataset(transactional_session, "latest_test")
    v1 = DatasetSchema(dataset_id=ds.id, version_num=1, schema={})
    v2 = DatasetSchema(dataset_id=ds.id, version_num=2, schema={})
    v3 = DatasetSchema(dataset_id=ds.id, version_num=3, schema={})
    transactional_session.add_all([v1, v2, v3])
    await transactional_session.flush()

    repo = DatasetSchemaRepository(transactional_session)
    latest = await repo.latest_for_dataset(ds.id)
    assert latest is not None
    assert latest.id == v3.id
    assert latest.version_num == 3


@pytest.mark.asyncio
async def test_latest_for_dataset_returns_none_when_no_schema(
    transactional_session: AsyncSession,
):
    ds = await _make_dataset(transactional_session, "latest_none")
    repo = DatasetSchemaRepository(transactional_session)
    assert await repo.latest_for_dataset(ds.id) is None
