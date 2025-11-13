import uuid

from sqlalchemy import select
from sqlalchemy.orm import with_polymorphic

from backend.models.dataset import Dataset
from backend.repositories.base import BaseRepository


class DatasetRepository(BaseRepository[Dataset]):
    model = Dataset

    async def get(self, obj_id: uuid.UUID) -> Dataset | None:
        """Get a dataset by ID with polymorphic loading."""
        # Use with_polymorphic to ensure all child table fields are loaded
        polymorphic_query = with_polymorphic(Dataset, "*")
        stmt = select(polymorphic_query).where(polymorphic_query.id == obj_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_multi_paginated(
        self, *, skip: int = 0, limit: int = 100
    ) -> tuple[list[Dataset], int]:
        """Get multiple datasets with pagination and polymorphic loading."""
        from sqlalchemy import func

        polymorphic_query = with_polymorphic(Dataset, "*")

        # Total count
        total_query = select(func.count()).select_from(polymorphic_query)
        total_result = await self.session.execute(total_query)
        total = total_result.scalar_one()

        # Items with polymorphic loading
        items_query = (
            select(polymorphic_query)
            .order_by(polymorphic_query.id)
            .offset(skip)
            .limit(limit)
        )
        items_result = await self.session.execute(items_query)
        items = list(items_result.scalars().all())

        return items, total

    async def get_by_system_and_object_name(
        self, system_id: uuid.UUID, object_name: str
    ) -> Dataset | None:
        """Get a dataset by system_id and object_name with polymorphic loading."""
        polymorphic_query = with_polymorphic(Dataset, "*")
        stmt = select(polymorphic_query).where(
            polymorphic_query.system_id == system_id,
            polymorphic_query.object_name == object_name,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
