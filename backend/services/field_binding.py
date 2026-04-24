import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.field_binding import FieldBinding
from backend.repositories.field_binding import FieldBindingRepository
from backend.schemas.field_binding import (
    FieldBindingCreate,
    FieldBindingRead,
    FieldBindingUpdate,
)
from backend.services.base import GenericService


class FieldBindingService(
    GenericService[
        FieldBinding, FieldBindingCreate, FieldBindingUpdate, FieldBindingRead
    ]
):
    """
    Service for field binding related business logic.
    """

    def __init__(self):
        super().__init__(
            model=FieldBinding,
            repository=FieldBindingRepository,
            read_schema=FieldBindingRead,
            not_found_error_code=errors.FIELD_BINDING_NOT_FOUND,
        )

    async def _validate_dependencies(
        self,
        uow: UnitOfWork,
        field_id: uuid.UUID,
        dataset_schema_id: uuid.UUID,
        type_instance_id: uuid.UUID,
    ) -> None:
        if not await uow.fields.get(field_id):
            raise AppException(errors.FIELD_NOT_FOUND)
        if not await uow.dataset_schemas.get(dataset_schema_id):
            raise AppException(errors.DATASET_SCHEMA_NOT_FOUND)
        if not await uow.type_instances.get(type_instance_id):
            raise AppException(errors.TYPE_INSTANCE_NOT_FOUND)

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: FieldBindingCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(FieldBindingRepository, self._get_repository(uow.session))
        if await repo.get_by_field_and_schema(
            obj_in.field_id, obj_in.dataset_schema_id
        ):
            raise AppException(errors.FIELD_BINDING_FIELD_ID_ALREADY_EXISTS)
        if await repo.get_by_dataset_schema_and_position(
            obj_in.dataset_schema_id, obj_in.position
        ):
            raise AppException(errors.FIELD_BINDING_POSITION_ALREADY_EXISTS)

        await self._validate_dependencies(
            uow, obj_in.field_id, obj_in.dataset_schema_id, obj_in.type_instance_id
        )

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: FieldBinding,
        obj_in: FieldBindingUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        repo = cast(FieldBindingRepository, self._get_repository(uow.session))

        # Check for unique constraint violations if relevant fields are updated
        new_schema_id = update_data.get("dataset_schema_id", db_obj.dataset_schema_id)
        new_field_id = update_data.get("field_id", db_obj.field_id)
        new_position = update_data.get("position", db_obj.position)

        if new_schema_id != db_obj.dataset_schema_id or new_field_id != db_obj.field_id:
            existing = await repo.get_by_field_and_schema(new_field_id, new_schema_id)
            if existing and existing.id != db_obj.id:
                raise AppException(errors.FIELD_BINDING_FIELD_ID_ALREADY_EXISTS)

        if new_schema_id != db_obj.dataset_schema_id or new_position != db_obj.position:
            existing = await repo.get_by_dataset_schema_and_position(
                new_schema_id, new_position
            )
            if existing and existing.id != db_obj.id:
                raise AppException(errors.FIELD_BINDING_POSITION_ALREADY_EXISTS)

        # Check if foreign keys exist
        await self._validate_dependencies(
            uow,
            new_field_id,
            new_schema_id,
            update_data.get("type_instance_id", db_obj.type_instance_id),
        )
