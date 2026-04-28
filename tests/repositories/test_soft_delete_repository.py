import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SystemKind
from backend.repositories.system_kind import SystemKindRepository


@pytest.mark.asyncio
async def test_soft_delete_then_get_returns_none(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="SD_A", name="A")
    transactional_session.add(kind)
    await transactional_session.flush()
    repo = SystemKindRepository(transactional_session)

    await repo.delete(db_obj=kind)
    # default get filters out deleted
    assert await repo.get(kind.id) is None


@pytest.mark.asyncio
async def test_get_including_deleted_returns_row(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="SD_B", name="B")
    transactional_session.add(kind)
    await transactional_session.flush()
    repo = SystemKindRepository(transactional_session)
    await repo.delete(db_obj=kind)

    found = await repo.get_including_deleted(kind.id)
    assert found is not None
    assert found.deleted_at is not None


@pytest.mark.asyncio
async def test_restore_clears_deleted_at(transactional_session: AsyncSession):
    kind = SystemKind(code="SD_C", name="C")
    transactional_session.add(kind)
    await transactional_session.flush()
    repo = SystemKindRepository(transactional_session)
    await repo.delete(db_obj=kind)

    restored = await repo.restore(db_obj=kind)
    assert restored.deleted_at is None
    # standard get works again
    assert await repo.get(kind.id) is not None


@pytest.mark.asyncio
async def test_get_multi_excludes_deleted_by_default(
    transactional_session: AsyncSession,
):
    a = SystemKind(code="SD_D", name="D")
    b = SystemKind(code="SD_E", name="E")
    transactional_session.add_all([a, b])
    await transactional_session.flush()
    repo = SystemKindRepository(transactional_session)
    await repo.delete(db_obj=a)

    items = await repo.get_multi()
    codes = {i.code for i in items}
    assert "SD_E" in codes
    assert "SD_D" not in codes


@pytest.mark.asyncio
async def test_get_multi_paginated_include_deleted(
    transactional_session: AsyncSession,
):
    a = SystemKind(code="SD_F", name="F")
    b = SystemKind(code="SD_G", name="G")
    transactional_session.add_all([a, b])
    await transactional_session.flush()
    repo = SystemKindRepository(transactional_session)
    await repo.delete(db_obj=a)

    items, total = await repo.get_multi_paginated(include_deleted=True)
    codes = {i.code for i in items}
    assert {"SD_F", "SD_G"}.issubset(codes)
    assert total >= 2

    # without flag — only non-deleted
    items, total = await repo.get_multi_paginated(include_deleted=False)
    codes = {i.code for i in items}
    assert "SD_F" not in codes
    assert "SD_G" in codes
