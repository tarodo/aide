import time
from typing import Any, Generic, Sequence, Type, TypeVar

import structlog
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.settings import settings
from backend.db.base import Base

logger = structlog.get_logger(__name__)

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic repository with basic CRUD operations.
    """

    model: Type[ModelType]

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _execute(self, stmt: Any, *, method: str = "unknown") -> Any:
        start = time.perf_counter()
        result = await self.session.execute(stmt)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms >= settings.SLOW_QUERY_THRESHOLD_MS:
            logger.warning(
                "Slow query detected",
                duration_ms=round(elapsed_ms, 2),
                table=self.model.__tablename__,
                method=method,
            )
        return result

    def _apply_filters(
        self, query: Select, filters: dict[str, Any], *, entity: Any = None
    ) -> Select:
        target = entity or self.model
        for field_name, value in filters.items():
            column = getattr(target, field_name, None)
            if column is None:
                raise ValueError(f"Model has no column '{field_name}'")
            query = query.where(column == value)
        return query

    def _apply_sort(
        self, query: Select, sort: list[tuple[str, bool]], *, entity: Any = None
    ) -> Select:
        target = entity or self.model
        for field_name, desc in sort:
            column = getattr(target, field_name, None)
            if column is None:
                raise ValueError(f"Model has no column '{field_name}'")
            query = query.order_by(column.desc() if desc else column.asc())
        return query

    async def get(self, obj_id: Any) -> ModelType | None:
        return await self.session.get(self.model, obj_id)

    async def get_multi(
        self, *, skip: int = 0, limit: int = 100
    ) -> Sequence[ModelType]:
        query = select(self.model).offset(skip).limit(limit)
        result = await self._execute(query, method="get_multi")
        return result.scalars().all()

    async def get_multi_paginated(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        sort: list[tuple[str, bool]] | None = None,
    ) -> tuple[Sequence[ModelType], int]:
        total_query = select(func.count()).select_from(self.model)
        if filters:
            total_query = self._apply_filters(total_query, filters)
        total_result = await self._execute(
            total_query, method="get_multi_paginated.count"
        )
        total = total_result.scalar_one()

        items_query = select(self.model)
        if filters:
            items_query = self._apply_filters(items_query, filters)
        if sort:
            items_query = self._apply_sort(items_query, sort)
        else:
            items_query = items_query.order_by(self.model.id)  # type: ignore[attr-defined]
        items_query = items_query.offset(skip).limit(limit)

        items_result = await self._execute(items_query, method="get_multi_paginated")
        items = items_result.scalars().all()

        return items, total

    async def create(self, *, obj_in: ModelType) -> ModelType:
        self.session.add(obj_in)
        await self.session.flush()
        await self.session.refresh(obj_in)
        return obj_in

    async def update(self, *, db_obj: ModelType) -> ModelType:
        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def delete(self, *, db_obj: ModelType) -> ModelType:
        await self.session.delete(db_obj)
        await self.session.flush()
        return db_obj


SoftDeleteModelType = TypeVar("SoftDeleteModelType", bound=Base)


class SoftDeleteRepository(BaseRepository[SoftDeleteModelType]):
    """Repository with soft-delete support. Filters out deleted rows by default."""

    async def get(self, obj_id: Any) -> SoftDeleteModelType | None:
        query = select(self.model).where(
            self.model.id == obj_id,  # type: ignore[attr-defined]
            self.model.deleted_at.is_(None),  # type: ignore[attr-defined]
        )
        result = await self._execute(query, method="get")
        return result.scalars().first()

    async def get_including_deleted(self, obj_id: Any) -> SoftDeleteModelType | None:
        return await self.session.get(self.model, obj_id)

    async def get_multi(
        self, *, skip: int = 0, limit: int = 100
    ) -> Sequence[SoftDeleteModelType]:
        query = (
            select(self.model)
            .where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
            .offset(skip)
            .limit(limit)
        )
        result = await self._execute(query, method="get_multi")
        return result.scalars().all()

    async def get_multi_paginated(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        sort: list[tuple[str, bool]] | None = None,
    ) -> tuple[Sequence[SoftDeleteModelType], int]:
        total_query = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        )
        if filters:
            total_query = self._apply_filters(total_query, filters)
        total_result = await self._execute(
            total_query, method="get_multi_paginated.count"
        )
        total = total_result.scalar_one()

        items_query = select(self.model).where(
            self.model.deleted_at.is_(None)  # type: ignore[attr-defined]
        )
        if filters:
            items_query = self._apply_filters(items_query, filters)
        if sort:
            items_query = self._apply_sort(items_query, sort)
        else:
            items_query = items_query.order_by(self.model.id)  # type: ignore[attr-defined]
        items_query = items_query.offset(skip).limit(limit)

        items_result = await self._execute(items_query, method="get_multi_paginated")
        items = items_result.scalars().all()
        return items, total

    async def delete(self, *, db_obj: SoftDeleteModelType) -> SoftDeleteModelType:
        db_obj.deleted_at = func.now()  # type: ignore[attr-defined]
        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def restore(self, *, db_obj: SoftDeleteModelType) -> SoftDeleteModelType:
        db_obj.deleted_at = None  # type: ignore[attr-defined]
        db_obj.deleted_by = None  # type: ignore[attr-defined]
        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj
