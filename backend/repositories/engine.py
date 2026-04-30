import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import with_polymorphic

from backend.models.engine import Engine
from backend.repositories.base import SoftDeleteRepository


class EngineRepository(SoftDeleteRepository[Engine]):
    model = Engine

    async def get(self, obj_id: uuid.UUID) -> Engine | None:
        poly = with_polymorphic(Engine, "*")
        stmt = select(poly).where(
            poly.id == obj_id,
            poly.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_including_deleted(self, obj_id: uuid.UUID) -> Engine | None:
        poly = with_polymorphic(Engine, "*")
        stmt = select(poly).where(poly.id == obj_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_code(self, code: str) -> Engine | None:
        poly = with_polymorphic(Engine, "*")
        stmt = select(poly).where(
            poly.code == code,
            poly.deleted_at.is_(None),
        )
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
    ) -> tuple[list[Engine], int]:
        poly = with_polymorphic(Engine, "*")

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
            items_query = items_query.order_by(poly.created_at.desc())
        items_query = items_query.offset(skip).limit(limit)

        items_result = await self.session.execute(items_query)
        items = list(items_result.scalars().all())
        return items, total
