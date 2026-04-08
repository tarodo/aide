import uuid
from typing import cast

from sqlalchemy import func, select

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.data_type import DataType
from backend.models.system import System
from backend.models.system_flavor import SystemFlavor
from backend.repositories.system_flavor import SystemFlavorRepository
from backend.schemas.system_flavor import (
    SystemFlavorCreate,
    SystemFlavorRead,
    SystemFlavorUpdate,
)
from backend.services.base import SoftDeleteService


class SystemFlavorService(
    SoftDeleteService[
        SystemFlavor, SystemFlavorCreate, SystemFlavorUpdate, SystemFlavorRead
    ]
):
    """
    Service for system flavor related business logic.
    """

    def __init__(self):
        super().__init__(
            model=SystemFlavor,
            repository=SystemFlavorRepository,
            read_schema=SystemFlavorRead,
            not_found_error_code=errors.SYSTEM_FLAVOR_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: SystemFlavorCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(SystemFlavorRepository, self._get_repository(uow.session))
        if await repo.get_by_code(obj_in.code):
            raise AppException(errors.SYSTEM_FLAVOR_ALREADY_EXISTS)
        if not await uow.system_kinds.get(obj_in.kind_id):
            raise AppException(errors.SYSTEM_KIND_NOT_FOUND)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: SystemFlavor,
        obj_in: SystemFlavorUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        if "code" in update_data and update_data["code"] != db_obj.code:
            repo = cast(SystemFlavorRepository, self._get_repository(uow.session))
            if await repo.get_by_code(update_data["code"]):
                raise AppException(errors.SYSTEM_FLAVOR_ALREADY_EXISTS)
        if "kind_id" in update_data:
            if not await uow.system_kinds.get(update_data["kind_id"]):
                raise AppException(errors.SYSTEM_KIND_NOT_FOUND)

    async def _pre_delete(self, uow: UnitOfWork, db_obj: SystemFlavor) -> None:
        # Check for non-deleted Systems
        systems_count = await uow.session.execute(
            select(func.count())
            .select_from(System)
            .where(System.flavor_id == db_obj.id, System.deleted_at.is_(None))
        )
        if systems_count.scalar_one() > 0:
            raise AppException(errors.HAS_DEPENDENT_ENTITIES)

        # Check for non-deleted DataTypes
        dt_count = await uow.session.execute(
            select(func.count())
            .select_from(DataType)
            .where(
                DataType.system_flavor_id == db_obj.id,
                DataType.deleted_at.is_(None),
            )
        )
        if dt_count.scalar_one() > 0:
            raise AppException(errors.HAS_DEPENDENT_ENTITIES)
