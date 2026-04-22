import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.repositories.dataset_link import DatasetLinkRepository


async def _make_system(session: AsyncSession, *, code_suffix: str) -> System:
    kind = SystemKind(code=f"KIND_DLR_{code_suffix}", name=f"Kind DLR {code_suffix}")
    flavor = SystemFlavor(
        code=f"FL_DLR_{code_suffix}", name=f"Flavor DLR {code_suffix}", kind=kind
    )
    system = System(
        code=f"SYS_DLR_{code_suffix}", name=f"System DLR {code_suffix}", flavor=flavor
    )
    session.add_all([kind, flavor, system])
    await session.flush()
    return system


@pytest.mark.asyncio
async def test_has_active_links_for_dataset(transactional_session: AsyncSession):
    seeded_system = await _make_system(transactional_session, code_suffix="HAS")
    src = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="s",
        kind="rdbms",
        schema_name="s",
        table_name="s",
    )
    tgt = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="t",
        kind="rdbms",
        schema_name="s",
        table_name="t",
    )
    transactional_session.add_all([src, tgt])
    await transactional_session.flush()

    repo = DatasetLinkRepository(transactional_session)
    assert await repo.has_active_links_for_dataset(src.id) is False

    link = DatasetLink(source_dataset_id=src.id, target_dataset_id=tgt.id)
    transactional_session.add(link)
    await transactional_session.flush()

    assert await repo.has_active_links_for_dataset(src.id) is True
    assert await repo.has_active_links_for_dataset(tgt.id) is True


@pytest.mark.asyncio
async def test_get_active_between(transactional_session: AsyncSession):
    seeded_system = await _make_system(transactional_session, code_suffix="BTW")
    a = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="a",
        kind="rdbms",
        schema_name="s",
        table_name="a",
    )
    b = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="b",
        kind="rdbms",
        schema_name="s",
        table_name="b",
    )
    transactional_session.add_all([a, b])
    await transactional_session.flush()

    repo = DatasetLinkRepository(transactional_session)
    assert await repo.get_active_between(a.id, b.id) is None

    link = DatasetLink(source_dataset_id=a.id, target_dataset_id=b.id)
    transactional_session.add(link)
    await transactional_session.flush()

    found = await repo.get_active_between(a.id, b.id)
    assert found is not None and found.id == link.id


@pytest.mark.asyncio
async def test_list_by_source_and_target(transactional_session: AsyncSession):
    seeded_system = await _make_system(transactional_session, code_suffix="LST")
    a = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="a1",
        kind="rdbms",
        schema_name="s",
        table_name="a1",
    )
    b = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="b1",
        kind="rdbms",
        schema_name="s",
        table_name="b1",
    )
    c = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="c1",
        kind="rdbms",
        schema_name="s",
        table_name="c1",
    )
    transactional_session.add_all([a, b, c])
    await transactional_session.flush()
    transactional_session.add(
        DatasetLink(source_dataset_id=a.id, target_dataset_id=b.id)
    )
    transactional_session.add(
        DatasetLink(source_dataset_id=a.id, target_dataset_id=c.id)
    )
    transactional_session.add(
        DatasetLink(source_dataset_id=b.id, target_dataset_id=c.id)
    )
    await transactional_session.flush()

    repo = DatasetLinkRepository(transactional_session)
    downstream_of_a = await repo.list_by_source(a.id)
    upstream_of_c = await repo.list_by_target(c.id)
    assert len(downstream_of_a) == 2
    assert len(upstream_of_c) == 2
