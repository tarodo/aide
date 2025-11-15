import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.field import Field
from backend.repositories.field import FieldRepository
from backend.schemas.field import (
    FieldCreate,
    FieldRead,
    FieldUpdate,
)
from backend.services.base import GenericService


class FieldService(GenericService[Field, FieldCreate, FieldUpdate, FieldRead]):
    """
    Service for field related business logic.
    """

    def __init__(self):
        super().__init__(
            model=Field,
            repository=FieldRepository,
            read_schema=FieldRead,
            not_found_error_code=errors.FIELD_NOT_FOUND,
        )

    async def _validate_dependencies(
        self, uow: UnitOfWork, dataset_id: uuid.UUID
    ) -> None:
        if not await uow.datasets.get(dataset_id):
            raise AppException(errors.DATASET_NOT_FOUND)

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: FieldCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(FieldRepository, self._get_repository(uow.session))
        if await repo.get_by_dataset_and_name(obj_in.dataset_id, obj_in.name):
            raise AppException(errors.FIELD_ALREADY_EXISTS)
        await self._validate_dependencies(uow, obj_in.dataset_id)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: Field,
        obj_in: FieldUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        repo = cast(FieldRepository, self._get_repository(uow.session))

        current_dataset_id = db_obj.dataset_id
        current_name = db_obj.name
        new_dataset_id = update_data.get("dataset_id", current_dataset_id)
        new_name = update_data.get("name", current_name)

        if new_dataset_id != current_dataset_id or new_name != current_name:
            if await repo.get_by_dataset_and_name(new_dataset_id, new_name):
                raise AppException(errors.FIELD_ALREADY_EXISTS)

        if "dataset_id" in update_data:
            await self._validate_dependencies(uow, new_dataset_id)
