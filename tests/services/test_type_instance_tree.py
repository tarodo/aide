from __future__ import annotations

import uuid

import pytest

from backend.models.data_type import DataType
from backend.models.system_flavor import SystemFlavor
from backend.models.system_kind import SystemKind
from backend.models.type_instance import TypeInstance
from backend.services.type_instance_tree import (
    PlanNode,
    create_tree,
)


async def _make_kind_flavor_types(session) -> dict[str, uuid.UUID]:
    kind = SystemKind(code="rdbms", name="Relational")
    session.add(kind)
    await session.flush()
    flavor = SystemFlavor(code="pg", name="PG", kind_id=kind.id, versions=["14"])
    session.add(flavor)
    await session.flush()
    out: dict[str, uuid.UUID] = {}
    for code in ("array", "integer", "decimal"):
        dt = DataType(
            system_flavor_id=flavor.id,
            code=code,
            params_schema={},
            render_template=code,
        )
        session.add(dt)
        await session.flush()
        out[code] = dt.id
    return out


@pytest.mark.asyncio
async def test_create_tree_leaf(transactional_session) -> None:
    types = await _make_kind_flavor_types(transactional_session)
    plan = PlanNode(
        data_type_id=types["integer"],
        type_params={},
        slot=None,
        children=[],
    )
    root_id = await create_tree(transactional_session, plan)
    assert isinstance(root_id, uuid.UUID)
    row = await transactional_session.get(TypeInstance, root_id)
    assert row.data_type_id == types["integer"]
    assert row.parent_id is None
    assert row.slot is None


@pytest.mark.asyncio
async def test_create_tree_with_child(transactional_session) -> None:
    types = await _make_kind_flavor_types(transactional_session)
    plan = PlanNode(
        data_type_id=types["array"],
        type_params={},
        slot=None,
        children=[
            PlanNode(
                data_type_id=types["integer"],
                type_params={},
                slot="item",
                children=[],
            )
        ],
    )
    root_id = await create_tree(transactional_session, plan)
    root = await transactional_session.get(TypeInstance, root_id)
    assert root.data_type_id == types["array"]
    # Find the child by parent_id.
    from sqlalchemy import select

    children = (
        (
            await transactional_session.execute(
                select(TypeInstance).where(TypeInstance.parent_id == root_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(children) == 1
    assert children[0].data_type_id == types["integer"]
    assert children[0].slot == "item"


@pytest.mark.asyncio
async def test_create_tree_passes_type_params(transactional_session) -> None:
    types = await _make_kind_flavor_types(transactional_session)
    plan = PlanNode(
        data_type_id=types["decimal"],
        type_params={"precision": 10, "scale": 2},
        slot=None,
        children=[],
    )
    root_id = await create_tree(transactional_session, plan)
    row = await transactional_session.get(TypeInstance, root_id)
    assert row.type_params == {"precision": 10, "scale": 2}
