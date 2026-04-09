import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.models.field import Field
from backend.repositories.base import BaseRepository


class FieldRepository(BaseRepository[Field]):
    model = Field

    async def get_by_dataset_and_name(
        self, dataset_id: uuid.UUID, name: str, parent_id: uuid.UUID | None = None
    ) -> Field | None:
        """Get a field by dataset_id, parent_id, and name (sibling uniqueness)."""
        stmt = select(self.model).where(
            self.model.dataset_id == dataset_id,
            self.model.name == name,
        )
        if parent_id is None:
            stmt = stmt.where(self.model.parent_id.is_(None))
        else:
            stmt = stmt.where(self.model.parent_id == parent_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_children(self, parent_id: uuid.UUID) -> Sequence[Field]:
        """Get direct children of a field."""
        stmt = select(self.model).where(self.model.parent_id == parent_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_roots(self, dataset_id: uuid.UUID) -> Sequence[Field]:
        """Get root-level fields (parent_id IS NULL) for a dataset."""
        stmt = select(self.model).where(
            self.model.dataset_id == dataset_id,
            self.model.parent_id.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_tree(self, dataset_id: uuid.UUID) -> Sequence[Field]:
        """Load all root fields for a dataset with their full subtree."""

        def _recursive_children(depth: int = 5):
            if depth <= 0:
                return selectinload(Field.children)
            return selectinload(Field.children).options(_recursive_children(depth - 1))

        stmt = (
            select(self.model)
            .where(
                self.model.dataset_id == dataset_id,
                self.model.parent_id.is_(None),
            )
            .options(_recursive_children())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
