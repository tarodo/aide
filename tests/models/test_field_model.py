import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.field import Field


async def _seed_dataset(session: AsyncSession) -> DatasetRdbms:
    kind = SystemKind(code="RDBMS_ORIGIN", name="RDBMS Origin")
    flavor = SystemFlavor(code="PG_ORIGIN", name="PG Origin", kind=kind)
    system = System(code="SYS_ORIGIN", name="System Origin", flavor=flavor)
    ds = DatasetRdbms(
        system=system, object_name="o", kind="rdbms", schema_name="s", table_name="t"
    )
    session.add_all([kind, flavor, system, ds])
    await session.flush()
    return ds


@pytest.mark.asyncio
async def test_field_origin_default_is_mapped(transactional_session: AsyncSession):
    ds = await _seed_dataset(transactional_session)
    f = Field(dataset_id=ds.id, name="col")
    transactional_session.add(f)
    await transactional_session.flush()
    await transactional_session.refresh(f)
    assert f.origin == "mapped"


@pytest.mark.asyncio
async def test_field_origin_accepts_all_states(transactional_session: AsyncSession):
    ds = await _seed_dataset(transactional_session)
    for origin in ("mapped", "tech", "deprecated"):
        f = Field(dataset_id=ds.id, name=f"col_{origin}", origin=origin)
        transactional_session.add(f)
    await transactional_session.flush()
