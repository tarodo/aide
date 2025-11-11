import math
import uuid

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.system_flavor import SystemFlavor
from backend.schemas.pagination import Page
from backend.schemas.system_flavor import (
    SystemFlavorCreate,
    SystemFlavorRead,
    SystemFlavorUpdate,
)


class SystemFlavorService:
    """
    Service for system flavor related business logic.
    """

    async def create_system_flavor(
        self,
        uow: UnitOfWork,
        system_flavor_in: SystemFlavorCreate,
        creator_id: uuid.UUID,
    ) -> SystemFlavorRead:
        """
        Create a new system flavor.
        """
        system_flavor_data = system_flavor_in.model_dump()

        async with uow:
            if await uow.system_flavors.get_by_code(system_flavor_in.code):
                raise AppException(errors.SYSTEM_FLAVOR_ALREADY_EXISTS)

            if not await uow.system_kinds.get(system_flavor_in.kind_id):
                raise AppException(errors.SYSTEM_KIND_NOT_FOUND)

            db_system_flavor = SystemFlavor(
                **system_flavor_data,
                created_by=creator_id,
                updated_by=creator_id,
            )
            db_system_flavor = await uow.system_flavors.create(obj_in=db_system_flavor)
            return SystemFlavorRead.model_validate(db_system_flavor)

    async def get_system_flavor(
        self, uow: UnitOfWork, system_flavor_id: uuid.UUID
    ) -> SystemFlavorRead:
        """
        Get a system flavor by ID.
        """
        async with uow:
            db_system_flavor = await uow.system_flavors.get(system_flavor_id)
            if not db_system_flavor:
                raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)
            return SystemFlavorRead.model_validate(db_system_flavor)

    async def get_system_flavors_paginated(
        self, uow: UnitOfWork, *, page: int, size: int
    ) -> Page[SystemFlavorRead]:
        """
        Get a paginated list of system flavors.
        """
        skip = (page - 1) * size
        async with uow:
            items, total = await uow.system_flavors.get_multi_paginated(
                skip=skip, limit=size
            )
            pages = math.ceil(total / size) if size > 0 else 0

            return Page[SystemFlavorRead](
                items=[SystemFlavorRead.model_validate(item) for item in items],
                total=total,
                page=page,
                size=size,
                pages=pages,
            )

    async def update_system_flavor(
        self,
        uow: UnitOfWork,
        system_flavor_id: uuid.UUID,
        system_flavor_in: SystemFlavorUpdate,
        updater_id: uuid.UUID,
    ) -> SystemFlavorRead:
        """
        Update a system flavor.
        """
        update_data = system_flavor_in.model_dump(exclude_unset=True)

        async with uow:
            db_system_flavor = await uow.system_flavors.get(system_flavor_id)
            if not db_system_flavor:
                raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)

            if "code" in update_data and update_data["code"] != db_system_flavor.code:
                if await uow.system_flavors.get_by_code(update_data["code"]):
                    raise AppException(errors.SYSTEM_FLAVOR_ALREADY_EXISTS)

            if "kind_id" in update_data:
                if not await uow.system_kinds.get(update_data["kind_id"]):
                    raise AppException(errors.SYSTEM_KIND_NOT_FOUND)

            for field, value in update_data.items():
                setattr(db_system_flavor, field, value)

            db_system_flavor.updated_by = updater_id
            db_system_flavor = await uow.system_flavors.update(db_obj=db_system_flavor)
            return SystemFlavorRead.model_validate(db_system_flavor)

    async def delete_system_flavor(
        self, uow: UnitOfWork, system_flavor_id: uuid.UUID
    ) -> SystemFlavorRead:
        """
        Delete a system flavor.
        """
        async with uow:
            db_system_flavor = await uow.system_flavors.get(system_flavor_id)
            if not db_system_flavor:
                raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)

            deleted_system_flavor = await uow.system_flavors.delete(
                db_obj=db_system_flavor
            )
            return SystemFlavorRead.model_validate(deleted_system_flavor)
