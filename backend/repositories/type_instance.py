import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.models.type_instance import TypeInstance
from backend.repositories.base import BaseRepository


class TypeInstanceRepository(BaseRepository[TypeInstance]):
    model = TypeInstance

    async def get_by_parent_and_slot(
        self, parent_id: uuid.UUID, slot: str
    ) -> TypeInstance | None:
        stmt = select(self.model).where(
            self.model.parent_id == parent_id,
            self.model.slot == slot,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_children(self, parent_id: uuid.UUID) -> Sequence[TypeInstance]:
        stmt = select(self.model).where(self.model.parent_id == parent_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_tree(self, root_id: uuid.UUID) -> TypeInstance | None:
        """Load a type instance with its full tree using recursive eager loading."""

        def _recursive_children(depth: int = 5):
            """Build nested selectinload options for recursive children."""
            if depth <= 0:
                return selectinload(TypeInstance.children)
            return selectinload(TypeInstance.children).options(
                _recursive_children(depth - 1)
            )

        stmt = (
            select(self.model)
            .where(self.model.id == root_id)
            .options(_recursive_children())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
