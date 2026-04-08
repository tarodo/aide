import uuid
from typing import cast

from sqlalchemy import func, select

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.system_flavor import SystemFlavor
from backend.models.system_kind import SystemKind
from backend.repositories.system_kind import SystemKindRepository
from backend.schemas.system_kind import (
    SystemKindCreate,
    SystemKindRead,
    SystemKindUpdate,
)
from backend.services.base import SoftDeleteService


class SystemKindService(
    SoftDeleteService[SystemKind, SystemKindCreate, SystemKindUpdate, SystemKindRead]
):
    """
    Service for system kind related business logic.
    """

    def __init__(self):
        super().__init__(
            model=SystemKind,
            repository=SystemKindRepository,
            read_schema=SystemKindRead,
            not_found_error_code=errors.SYSTEM_KIND_NOT_FOUND,
        )

    async def _pre_create(
        self, uow: UnitOfWork, obj_in: SystemKindCreate, creator_id: uuid.UUID | None
    ) -> None:
        repo = cast(SystemKindRepository, self._get_repository(uow.session))
        if await repo.get_by_code(obj_in.code):
            raise AppException(errors.SYSTEM_KIND_ALREADY_EXISTS)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: SystemKind,
        obj_in: SystemKindUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        if "code" in update_data and update_data["code"] != db_obj.code:
            repo = cast(SystemKindRepository, self._get_repository(uow.session))
            if await repo.get_by_code(update_data["code"]):
                raise AppException(errors.SYSTEM_KIND_ALREADY_EXISTS)

    async def _pre_delete(self, uow: UnitOfWork, db_obj: SystemKind) -> None:
        count_query = (
            select(func.count())
            .select_from(SystemFlavor)
            .where(
                SystemFlavor.kind_id == db_obj.id,
                SystemFlavor.deleted_at.is_(None),
            )
        )
        result = await uow.session.execute(count_query)
        if result.scalar_one() > 0:
            raise AppException(errors.HAS_DEPENDENT_ENTITIES)
