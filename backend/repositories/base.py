from typing import Any, Generic, Sequence, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic repository with basic CRUD operations.
    """

    model: Type[ModelType]

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, obj_id: Any) -> ModelType | None:
        """
        Get an object by its ID.

        :param obj_id: Object ID
        :return: The object or None if not found
        """
        return await self.session.get(self.model, obj_id)

    async def get_multi(
        self, *, skip: int = 0, limit: int = 100
    ) -> Sequence[ModelType]:
        """
        Get multiple objects with pagination.

        :param skip: Number of objects to skip
        :param limit: Maximum number of objects to return
        :return: List of objects
        """
        query = select(self.model).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_multi_paginated(
        self, *, skip: int = 0, limit: int = 100
    ) -> tuple[Sequence[ModelType], int]:
        """
        Get multiple objects with pagination and total count.

        :param skip: Number of objects to skip
        :param limit: Maximum number of objects to return
        :return: A tuple containing the list of objects and the total count
        """
        total_query = select(func.count()).select_from(self.model)
        total_result = await self.session.execute(total_query)
        total = total_result.scalar_one()

        # Assuming the model has an 'id' attribute for ordering.
        items_query = (
            select(self.model).order_by(self.model.id).offset(skip).limit(limit)  # type: ignore[attr-defined]
        )
        items_result = await self.session.execute(items_query)
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
