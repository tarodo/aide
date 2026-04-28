from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.type_instance import TypeInstance


@dataclass
class PlanNode:
    """Server-side plan for one TypeInstance node.

    A leaf has children=[]. The root's `slot` is conventionally None
    (it has no parent). Children carry their slot relative to the parent.
    """

    data_type_id: uuid.UUID
    type_params: dict[str, Any]
    slot: str | None
    children: list["PlanNode"] = field(default_factory=list)


async def create_tree(session: AsyncSession, plan: PlanNode) -> uuid.UUID:
    """Persist a TypeInstance tree depth-first.

    Returns the id of the root TypeInstance.
    """
    return await _create_node(session, plan, parent_id=None)


async def _create_node(
    session: AsyncSession, plan: PlanNode, parent_id: uuid.UUID | None
) -> uuid.UUID:
    row = TypeInstance(
        data_type_id=plan.data_type_id,
        type_params=plan.type_params or None,
        parent_id=parent_id,
        slot=plan.slot,
    )
    session.add(row)
    await session.flush()
    for child in plan.children:
        await _create_node(session, child, parent_id=row.id)
    return row.id
