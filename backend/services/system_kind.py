import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.system_kind import SystemKind
from backend.repositories.system_kind import SystemKindRepository
from backend.schemas.system_kind import (
    SystemKindCreate,
    SystemKindRead,
    SystemKindUpdate,
)
from backend.services.base import GenericService


class SystemKindService(
    GenericService[SystemKind, SystemKindCreate, SystemKindUpdate, SystemKindRead]
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
