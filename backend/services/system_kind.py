import math
import uuid

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.system_kind import SystemKind
from backend.schemas.pagination import Page
from backend.schemas.system_kind import (
    SystemKindCreate,
    SystemKindRead,
    SystemKindUpdate,
)


class SystemKindService:
    """
    Service for system kind related business logic.
    """

    async def create_system_kind(
        self, uow: UnitOfWork, system_kind_in: SystemKindCreate, creator_id: uuid.UUID
    ) -> SystemKindRead:
        """
        Create a new system kind.
        """
        system_kind_data = system_kind_in.model_dump()

        async with uow:
            if await uow.system_kinds.get_by_code(system_kind_in.code):
                raise AppException(errors.SYSTEM_KIND_ALREADY_EXISTS)

            db_system_kind = SystemKind(
                **system_kind_data,
                created_by=creator_id,
                updated_by=creator_id,
            )
            db_system_kind = await uow.system_kinds.create(obj_in=db_system_kind)
            return SystemKindRead.model_validate(db_system_kind)

    async def get_system_kind(
        self, uow: UnitOfWork, system_kind_id: uuid.UUID
    ) -> SystemKindRead:
        """
        Get a system kind by ID.
        """
        async with uow:
            db_system_kind = await uow.system_kinds.get(system_kind_id)
            if not db_system_kind:
                raise AppException(errors.SYSTEM_KIND_NOT_FOUND)
            return SystemKindRead.model_validate(db_system_kind)

    async def get_system_kinds_paginated(
        self, uow: UnitOfWork, *, page: int, size: int
    ) -> Page[SystemKindRead]:
        """
        Get a paginated list of system kinds.
        """
        skip = (page - 1) * size
        async with uow:
            items, total = await uow.system_kinds.get_multi_paginated(
                skip=skip, limit=size
            )
            pages = math.ceil(total / size) if size > 0 else 0

            return Page[SystemKindRead](
                items=[SystemKindRead.model_validate(item) for item in items],
                total=total,
                page=page,
                size=size,
                pages=pages,
            )

    async def update_system_kind(
        self,
        uow: UnitOfWork,
        system_kind_id: uuid.UUID,
        system_kind_in: SystemKindUpdate,
        updater_id: uuid.UUID,
    ) -> SystemKindRead:
        """
        Update a system kind.
        """
        update_data = system_kind_in.model_dump(exclude_unset=True)

        async with uow:
            db_system_kind = await uow.system_kinds.get(system_kind_id)
            if not db_system_kind:
                raise AppException(errors.SYSTEM_KIND_NOT_FOUND)

            if "code" in update_data and update_data["code"] != db_system_kind.code:
                if await uow.system_kinds.get_by_code(update_data["code"]):
                    raise AppException(errors.SYSTEM_KIND_ALREADY_EXISTS)

            for field, value in update_data.items():
                setattr(db_system_kind, field, value)

            db_system_kind.updated_by = updater_id
            db_system_kind = await uow.system_kinds.update(db_obj=db_system_kind)
            return SystemKindRead.model_validate(db_system_kind)

    async def delete_system_kind(
        self, uow: UnitOfWork, system_kind_id: uuid.UUID
    ) -> SystemKindRead:
        """
        Delete a system kind.
        """
        async with uow:
            db_system_kind = await uow.system_kinds.get(system_kind_id)
            if not db_system_kind:
                raise AppException(errors.SYSTEM_KIND_NOT_FOUND)

            deleted_system_kind = await uow.system_kinds.delete(db_obj=db_system_kind)
            return SystemKindRead.model_validate(deleted_system_kind)
