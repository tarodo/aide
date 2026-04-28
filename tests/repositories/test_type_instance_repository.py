import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SystemFlavor, SystemKind
from backend.models.data_type import DataType
from backend.models.type_instance import TypeInstance
from backend.repositories.type_instance import TypeInstanceRepository


async def _seed_two_types(session: AsyncSession, suffix: str):
    kind = SystemKind(code=f"K_{suffix}", name=f"K {suffix}")
    flavor = SystemFlavor(
        code=f"F_{suffix}", name=f"F {suffix}", kind=kind, versions=["1"]
    )
    session.add_all([kind, flavor])
    await session.flush()
    array_dt = DataType(
        system_flavor_id=flavor.id,
        code=f"array_{suffix}",
        params_schema={},
    )
    int_dt = DataType(
        system_flavor_id=flavor.id,
        code=f"int_{suffix}",
        params_schema={},
    )
    session.add_all([array_dt, int_dt])
    await session.flush()
    return array_dt, int_dt


@pytest.mark.asyncio
async def test_get_by_parent_and_slot_match(transactional_session: AsyncSession):
    arr, leaf = await _seed_two_types(transactional_session, "PS1")
    parent = TypeInstance(data_type_id=arr.id, type_params=None, slot=None)
    transactional_session.add(parent)
    await transactional_session.flush()
    child = TypeInstance(
        data_type_id=leaf.id, type_params=None, slot="item", parent_id=parent.id
    )
    transactional_session.add(child)
    await transactional_session.flush()

    repo = TypeInstanceRepository(transactional_session)
    found = await repo.get_by_parent_and_slot(parent.id, "item")
    assert found is not None and found.id == child.id


@pytest.mark.asyncio
async def test_get_by_parent_and_slot_miss(transactional_session: AsyncSession):
    repo = TypeInstanceRepository(transactional_session)
    assert await repo.get_by_parent_and_slot(uuid.uuid4(), "nope") is None


@pytest.mark.asyncio
async def test_get_children_returns_all(transactional_session: AsyncSession):
    arr, leaf = await _seed_two_types(transactional_session, "GC1")
    parent = TypeInstance(data_type_id=arr.id, type_params=None, slot=None)
    transactional_session.add(parent)
    await transactional_session.flush()
    a = TypeInstance(
        data_type_id=leaf.id, type_params=None, slot="x", parent_id=parent.id
    )
    b = TypeInstance(
        data_type_id=leaf.id, type_params=None, slot="y", parent_id=parent.id
    )
    transactional_session.add_all([a, b])
    await transactional_session.flush()

    repo = TypeInstanceRepository(transactional_session)
    kids = await repo.get_children(parent.id)
    assert {c.id for c in kids} == {a.id, b.id}


@pytest.mark.asyncio
async def test_get_children_empty(transactional_session: AsyncSession):
    arr, _ = await _seed_two_types(transactional_session, "GC2")
    parent = TypeInstance(data_type_id=arr.id, type_params=None, slot=None)
    transactional_session.add(parent)
    await transactional_session.flush()

    repo = TypeInstanceRepository(transactional_session)
    assert list(await repo.get_children(parent.id)) == []


@pytest.mark.asyncio
async def test_get_tree_eager_loads_recursive_children(
    transactional_session: AsyncSession,
):
    arr, leaf = await _seed_two_types(transactional_session, "TR1")
    root = TypeInstance(data_type_id=arr.id, type_params=None, slot=None)
    transactional_session.add(root)
    await transactional_session.flush()
    mid = TypeInstance(
        data_type_id=arr.id, type_params=None, slot="item", parent_id=root.id
    )
    transactional_session.add(mid)
    await transactional_session.flush()
    leaf_ti = TypeInstance(
        data_type_id=leaf.id, type_params=None, slot="item", parent_id=mid.id
    )
    transactional_session.add(leaf_ti)
    await transactional_session.flush()

    repo = TypeInstanceRepository(transactional_session)
    tree = await repo.get_tree(root.id)

    assert tree is not None
    # Recursive eager load should not raise MissingGreenlet on traversal.
    assert len(tree.children) == 1
    assert tree.children[0].id == mid.id
    assert len(tree.children[0].children) == 1
    assert tree.children[0].children[0].id == leaf_ti.id


@pytest.mark.asyncio
async def test_get_tree_unknown_id_returns_none(transactional_session: AsyncSession):
    repo = TypeInstanceRepository(transactional_session)
    assert await repo.get_tree(uuid.uuid4()) is None
