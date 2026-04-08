import uuid
from typing import cast

from sqlalchemy import func, select

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.dataset import Dataset
from backend.models.system import System
from backend.repositories.system import SystemRepository
from backend.schemas.system import (
    SystemCreate,
    SystemRead,
    SystemUpdate,
)
from backend.services.base import SoftDeleteService


class SystemService(SoftDeleteService[System, SystemCreate, SystemUpdate, SystemRead]):
    """
    Service for system related business logic.
    """

    def __init__(self):
        super().__init__(
            model=System,
            repository=SystemRepository,
            read_schema=SystemRead,
            not_found_error_code=errors.SYSTEM_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: SystemCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(SystemRepository, self._get_repository(uow.session))
        if await repo.get_by_code(obj_in.code):
            raise AppException(errors.SYSTEM_ALREADY_EXISTS)
        if not await uow.system_flavors.get(obj_in.flavor_id):
            raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)
        if obj_in.credential_ref_id and not await uow.credential_refs.get(
            obj_in.credential_ref_id
        ):
            raise AppException(errors.CREDENTIAL_REF_NOT_FOUND)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: System,
        obj_in: SystemUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        if "code" in update_data and update_data["code"] != db_obj.code:
            repo = cast(SystemRepository, self._get_repository(uow.session))
            if await repo.get_by_code(update_data["code"]):
                raise AppException(errors.SYSTEM_ALREADY_EXISTS)
        if "flavor_id" in update_data:
            if not await uow.system_flavors.get(update_data["flavor_id"]):
                raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)
        if "credential_ref_id" in update_data:
            if update_data["credential_ref_id"] and not await uow.credential_refs.get(
                update_data["credential_ref_id"]
            ):
                raise AppException(errors.CREDENTIAL_REF_NOT_FOUND)

    async def _pre_delete(self, uow: UnitOfWork, db_obj: System) -> None:
        count_query = (
            select(func.count())
            .select_from(Dataset)
            .where(
                Dataset.system_id == db_obj.id,
                Dataset.deleted_at.is_(None),
            )
        )
        result = await uow.session.execute(count_query)
        if result.scalar_one() > 0:
            raise AppException(errors.HAS_DEPENDENT_ENTITIES)
