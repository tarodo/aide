import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.data_type import DataType
from backend.repositories.data_type import DataTypeRepository
from backend.schemas.data_type import (
    DataTypeCreate,
    DataTypeRead,
    DataTypeUpdate,
)
from backend.services.base import GenericService


class DataTypeService(
    GenericService[DataType, DataTypeCreate, DataTypeUpdate, DataTypeRead]
):
    """
    Service for data type related business logic.
    """

    def __init__(self):
        super().__init__(
            model=DataType,
            repository=DataTypeRepository,
            read_schema=DataTypeRead,
            not_found_error_code=errors.DATA_TYPE_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: DataTypeCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(DataTypeRepository, self._get_repository(uow.session))
        if await repo.get_by_system_flavor_and_code(
            obj_in.system_flavor_id, obj_in.code
        ):
            raise AppException(errors.DATA_TYPE_ALREADY_EXISTS)
        if not await uow.system_flavors.get(obj_in.system_flavor_id):
            raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: DataType,
        obj_in: DataTypeUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        repo = cast(DataTypeRepository, self._get_repository(uow.session))

        current_flavor_id = db_obj.system_flavor_id
        current_code = db_obj.code
        new_flavor_id = update_data.get("system_flavor_id", current_flavor_id)
        new_code = update_data.get("code", current_code)

        if new_flavor_id != current_flavor_id or new_code != current_code:
            if await repo.get_by_system_flavor_and_code(new_flavor_id, new_code):
                raise AppException(errors.DATA_TYPE_ALREADY_EXISTS)

        if "system_flavor_id" in update_data:
            if not await uow.system_flavors.get(update_data["system_flavor_id"]):
                raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)
