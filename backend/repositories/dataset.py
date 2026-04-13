import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import with_polymorphic

from backend.models.dataset import Dataset
from backend.repositories.base import SoftDeleteRepository


class DatasetRepository(SoftDeleteRepository[Dataset]):
    model = Dataset

    async def get(self, obj_id: uuid.UUID) -> Dataset | None:
        """Get a non-deleted dataset by ID with polymorphic loading."""
        polymorphic_query = with_polymorphic(Dataset, "*")
        stmt = select(polymorphic_query).where(
            polymorphic_query.id == obj_id,
            polymorphic_query.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_including_deleted(self, obj_id: uuid.UUID) -> Dataset | None:
        """Get a dataset by ID regardless of deletion status."""
        polymorphic_query = with_polymorphic(Dataset, "*")
        stmt = select(polymorphic_query).where(polymorphic_query.id == obj_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_multi_paginated(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        sort: list[tuple[str, bool]] | None = None,
        include_deleted: bool = False,
    ) -> tuple[list[Dataset], int]:
        """Get multiple datasets with pagination and polymorphic loading."""
        poly = with_polymorphic(Dataset, "*")

        total_query = select(func.count()).select_from(poly)
        if not include_deleted:
            total_query = total_query.where(poly.deleted_at.is_(None))
        if filters:
            total_query = self._apply_filters(total_query, filters, entity=poly)
        total_result = await self.session.execute(total_query)
        total = total_result.scalar_one()

        items_query = select(poly)
        if not include_deleted:
            items_query = items_query.where(poly.deleted_at.is_(None))
        if filters:
            items_query = self._apply_filters(items_query, filters, entity=poly)
        if sort:
            items_query = self._apply_sort(items_query, sort, entity=poly)
        else:
            items_query = items_query.order_by(poly.id)
        items_query = items_query.offset(skip).limit(limit)

        items_result = await self.session.execute(items_query)
        items = list(items_result.scalars().all())

        return items, total

    async def get_by_system_and_object_name(
        self, system_id: uuid.UUID, object_name: str
    ) -> Dataset | None:
        """Get a non-deleted dataset by system_id and object_name with polymorphic loading."""
        polymorphic_query = with_polymorphic(Dataset, "*")
        stmt = select(polymorphic_query).where(
            polymorphic_query.system_id == system_id,
            polymorphic_query.object_name == object_name,
            polymorphic_query.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
