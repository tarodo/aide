import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SystemKind
from backend.repositories.system_kind import SystemKindRepository


@pytest.mark.asyncio
async def test_create_many_persists_all(transactional_session: AsyncSession):
    repo = SystemKindRepository(transactional_session)
    objs = [SystemKind(code=f"BATCH_{i}", name=f"Batch {i}") for i in range(3)]
    created = await repo.create_many(objs=objs)
    assert len(created) == 3
    for obj in created:
        assert obj.id is not None
    # Order preserved
    assert [o.code for o in created] == ["BATCH_0", "BATCH_1", "BATCH_2"]


@pytest.mark.asyncio
async def test_create_many_empty_returns_empty(transactional_session: AsyncSession):
    repo = SystemKindRepository(transactional_session)
    created = await repo.create_many(objs=[])
    assert created == []
