import math
import uuid

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.data_type import DataType
from backend.schemas.data_type import (
    DataTypeCreate,
    DataTypeRead,
    DataTypeUpdate,
)
from backend.schemas.pagination import Page


class DataTypeService:
    """
    Service for data type related business logic.
    """

    async def create_data_type(
        self,
        uow: UnitOfWork,
        data_type_in: DataTypeCreate,
        creator_id: uuid.UUID,
    ) -> DataTypeRead:
        """
        Create a new data type.
        """
        data_type_data = data_type_in.model_dump()

        async with uow:
            if await uow.data_types.get_by_system_flavor_and_code(
                data_type_in.system_flavor_id, data_type_in.code
            ):
                raise AppException(errors.DATA_TYPE_ALREADY_EXISTS)

            if not await uow.system_flavors.get(data_type_in.system_flavor_id):
                raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)

            db_data_type = DataType(
                **data_type_data,
                created_by=creator_id,
                updated_by=creator_id,
            )
            db_data_type = await uow.data_types.create(obj_in=db_data_type)
            return DataTypeRead.model_validate(db_data_type)

    async def get_data_type(
        self, uow: UnitOfWork, data_type_id: uuid.UUID
    ) -> DataTypeRead:
        """
        Get a data type by ID.
        """
        async with uow:
            db_data_type = await uow.data_types.get(data_type_id)
            if not db_data_type:
                raise AppException(errors.DATA_TYPE_NOT_FOUND)
            return DataTypeRead.model_validate(db_data_type)

    async def get_data_types_paginated(
        self, uow: UnitOfWork, *, page: int, size: int
    ) -> Page[DataTypeRead]:
        """
        Get a paginated list of data types.
        """
        skip = (page - 1) * size
        async with uow:
            items, total = await uow.data_types.get_multi_paginated(
                skip=skip, limit=size
            )
            pages = math.ceil(total / size) if size > 0 else 0

            return Page[DataTypeRead](
                items=[DataTypeRead.model_validate(item) for item in items],
                total=total,
                page=page,
                size=size,
                pages=pages,
            )

    async def update_data_type(
        self,
        uow: UnitOfWork,
        data_type_id: uuid.UUID,
        data_type_in: DataTypeUpdate,
        updater_id: uuid.UUID,
    ) -> DataTypeRead:
        """
        Update a data type.
        """
        update_data = data_type_in.model_dump(exclude_unset=True)

        async with uow:
            db_data_type = await uow.data_types.get(data_type_id)
            if not db_data_type:
                raise AppException(errors.DATA_TYPE_NOT_FOUND)

            current_flavor_id = db_data_type.system_flavor_id
            current_code = db_data_type.code

            new_flavor_id = update_data.get("system_flavor_id", current_flavor_id)
            new_code = update_data.get("code", current_code)

            if new_flavor_id != current_flavor_id or new_code != current_code:
                if await uow.data_types.get_by_system_flavor_and_code(
                    new_flavor_id, new_code
                ):
                    raise AppException(errors.DATA_TYPE_ALREADY_EXISTS)

            if "system_flavor_id" in update_data:
                if not await uow.system_flavors.get(update_data["system_flavor_id"]):
                    raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)

            for field, value in update_data.items():
                setattr(db_data_type, field, value)

            db_data_type.updated_by = updater_id
            db_data_type = await uow.data_types.update(db_obj=db_data_type)
            return DataTypeRead.model_validate(db_data_type)

    async def delete_data_type(
        self, uow: UnitOfWork, data_type_id: uuid.UUID
    ) -> DataTypeRead:
        """
        Delete a data type.
        """
        async with uow:
            db_data_type = await uow.data_types.get(data_type_id)
            if not db_data_type:
                raise AppException(errors.DATA_TYPE_NOT_FOUND)

            deleted_data_type = await uow.data_types.delete(db_obj=db_data_type)
            return DataTypeRead.model_validate(deleted_data_type)
