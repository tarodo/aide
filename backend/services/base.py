import math
import uuid
from typing import Any, Generic, Type, TypeVar, cast

import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import AppException
from backend.db.base import Base
from backend.db.uow import UnitOfWork
from backend.repositories.base import BaseRepository, SoftDeleteRepository
from backend.schemas.pagination import Page

logger = structlog.get_logger(__name__)

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)
ReadSchemaType = TypeVar("ReadSchemaType", bound=BaseModel)
RepositoryType = TypeVar("RepositoryType", bound=BaseRepository[Any])


class GenericService(
    Generic[ModelType, CreateSchemaType, UpdateSchemaType, ReadSchemaType]
):
    """
    Generic service with basic CRUD operations.
    """

    def __init__(
        self,
        model: Type[ModelType],
        repository: Type[RepositoryType],
        read_schema: Type[ReadSchemaType],
        not_found_error_code: str,
    ):
        self.model = model
        self.repository = repository
        self.read_schema = read_schema
        self.not_found_error_code = not_found_error_code

    @property
    def _entity_name(self) -> str:
        return self.model.__tablename__

    def _get_repository(self, session: AsyncSession) -> BaseRepository[ModelType]:
        return cast(BaseRepository[ModelType], self.repository(session))

    async def get_by_id(self, uow: UnitOfWork, obj_id: uuid.UUID) -> ReadSchemaType:
        """Get an object by its ID."""
        async with uow:
            repo: BaseRepository[ModelType] = self._get_repository(uow.session)
            db_obj = await repo.get(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)
            logger.debug(
                "entity.retrieved",
                entity=self._entity_name,
                entity_id=str(obj_id),
            )
            return self.read_schema.model_validate(db_obj)

    async def get_paginated(
        self,
        uow: UnitOfWork,
        *,
        page: int,
        size: int,
        filters: dict[str, Any] | None = None,
        sort: list[tuple[str, bool]] | None = None,
    ) -> Page[ReadSchemaType]:
        """Get a paginated list of objects."""
        skip = (page - 1) * size
        async with uow:
            repo: BaseRepository[ModelType] = self._get_repository(uow.session)
            items, total = await repo.get_multi_paginated(
                skip=skip, limit=size, filters=filters, sort=sort
            )
            pages = math.ceil(total / size) if size > 0 else 0
            logger.debug(
                "entity.listed",
                entity=self._entity_name,
                page=page,
                size=size,
                total=total,
            )

            return Page[ReadSchemaType](
                items=[self.read_schema.model_validate(item) for item in items],
                total=total,
                page=page,
                size=size,
                pages=pages,
            )

    async def _pre_create(
        self, uow: UnitOfWork, obj_in: CreateSchemaType, creator_id: uuid.UUID | None
    ) -> None:
        """Hook for pre-create validation."""
        pass

    async def create(
        self,
        uow: UnitOfWork,
        obj_in: CreateSchemaType,
        creator_id: uuid.UUID | None = None,
    ) -> ReadSchemaType:
        """Create a new object."""
        obj_in_data = obj_in.model_dump()
        async with uow:
            await self._pre_create(uow, obj_in, creator_id)
            repo: BaseRepository[ModelType] = self._get_repository(uow.session)
            db_obj = self.model(**obj_in_data)
            if creator_id and hasattr(db_obj, "created_by"):
                setattr(db_obj, "created_by", creator_id)
                setattr(db_obj, "updated_by", creator_id)

            created_obj = await repo.create(obj_in=db_obj)
            logger.info(
                "entity.created",
                entity=self._entity_name,
                entity_id=str(created_obj.id),  # type: ignore[attr-defined]
                user_id=str(creator_id) if creator_id else None,
            )
            return self.read_schema.model_validate(created_obj)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: ModelType,
        obj_in: UpdateSchemaType,
        updater_id: uuid.UUID | None,
    ) -> None:
        """Hook for pre-update validation."""
        pass

    async def update(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        obj_in: UpdateSchemaType,
        updater_id: uuid.UUID | None = None,
    ) -> ReadSchemaType:
        """Update an existing object."""
        update_data = obj_in.model_dump(exclude_unset=True)
        async with uow:
            repo: BaseRepository[ModelType] = self._get_repository(uow.session)
            db_obj = await repo.get(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)

            await self._pre_update(uow, db_obj, obj_in, updater_id)

            for field, value in update_data.items():
                setattr(db_obj, field, value)

            if updater_id and hasattr(db_obj, "updated_by"):
                setattr(db_obj, "updated_by", updater_id)

            updated_obj = await repo.update(db_obj=db_obj)
            logger.info(
                "entity.updated",
                entity=self._entity_name,
                entity_id=str(obj_id),
                user_id=str(updater_id) if updater_id else None,
            )
            return self.read_schema.model_validate(updated_obj)

    async def delete(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        deleter_id: uuid.UUID | None = None,
    ) -> ReadSchemaType:
        """Delete an object."""
        async with uow:
            repo: BaseRepository[ModelType] = self._get_repository(uow.session)
            db_obj = await repo.get(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)

            deleted_obj = await repo.delete(db_obj=db_obj)
            logger.info(
                "entity.deleted",
                entity=self._entity_name,
                entity_id=str(obj_id),
                user_id=str(deleter_id) if deleter_id else None,
            )
            return self.read_schema.model_validate(deleted_obj)


class SoftDeleteService(
    GenericService[ModelType, CreateSchemaType, UpdateSchemaType, ReadSchemaType]
):
    """Service with soft-delete and restore support."""

    def _get_repository(self, session: AsyncSession) -> SoftDeleteRepository[ModelType]:
        return cast(SoftDeleteRepository[ModelType], self.repository(session))

    async def _pre_delete(self, uow: UnitOfWork, db_obj: ModelType) -> None:
        """Hook for pre-delete validation (e.g. check for dependent children)."""
        pass

    async def delete(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        deleter_id: uuid.UUID | None = None,
    ) -> ReadSchemaType:
        """Soft-delete an object."""
        async with uow:
            repo = self._get_repository(uow.session)
            db_obj = await repo.get(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)

            await self._pre_delete(uow, db_obj)

            if deleter_id and hasattr(db_obj, "deleted_by"):
                setattr(db_obj, "deleted_by", deleter_id)

            deleted_obj = await repo.delete(db_obj=db_obj)
            logger.info(
                "entity.soft_deleted",
                entity=self._entity_name,
                entity_id=str(obj_id),
                user_id=str(deleter_id) if deleter_id else None,
            )
            return self.read_schema.model_validate(deleted_obj)

    async def restore(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        restorer_id: uuid.UUID | None = None,
    ) -> ReadSchemaType:
        """Restore a soft-deleted object."""
        async with uow:
            repo = self._get_repository(uow.session)
            db_obj = await repo.get_including_deleted(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)
            if not getattr(db_obj, "deleted_at", None):
                from backend.core.errors import ENTITY_NOT_DELETED

                raise AppException(ENTITY_NOT_DELETED)

            if restorer_id and hasattr(db_obj, "updated_by"):
                setattr(db_obj, "updated_by", restorer_id)

            restored_obj = await repo.restore(db_obj=db_obj)
            logger.info(
                "entity.restored",
                entity=self._entity_name,
                entity_id=str(obj_id),
                user_id=str(restorer_id) if restorer_id else None,
            )
            return self.read_schema.model_validate(restored_obj)
