import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.type_instance import TypeInstance
from backend.repositories.type_instance import TypeInstanceRepository
from backend.schemas.type_instance import (
    TypeInstanceCreate,
    TypeInstanceRead,
    TypeInstanceTree,
    TypeInstanceUpdate,
)
from backend.services.base import GenericService
from backend.services.params_schema_validator import validate_type_params


class TypeInstanceService(
    GenericService[
        TypeInstance, TypeInstanceCreate, TypeInstanceUpdate, TypeInstanceRead
    ]
):
    def __init__(self):
        super().__init__(
            model=TypeInstance,
            repository=TypeInstanceRepository,
            read_schema=TypeInstanceRead,
            not_found_error_code=errors.TYPE_INSTANCE_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: TypeInstanceCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        data_type = await uow.data_types.get(obj_in.data_type_id)
        if not data_type:
            raise AppException(errors.DATA_TYPE_NOT_FOUND)
        validate_type_params(data_type.params_schema or {}, obj_in.type_params)

        if obj_in.parent_id is not None:
            if obj_in.slot is None:
                raise AppException(errors.TYPE_INSTANCE_SLOT_REQUIRED)

            parent = await uow.type_instances.get(obj_in.parent_id)
            if not parent:
                raise AppException(errors.TYPE_INSTANCE_PARENT_NOT_FOUND)

            existing = await cast(
                TypeInstanceRepository, uow.type_instances
            ).get_by_parent_and_slot(obj_in.parent_id, obj_in.slot)
            if existing:
                raise AppException(errors.TYPE_INSTANCE_SLOT_ALREADY_EXISTS)
        else:
            if obj_in.slot is not None:
                raise AppException(errors.TYPE_INSTANCE_SLOT_FORBIDDEN)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: TypeInstance,
        obj_in: TypeInstanceUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        if "type_params" in update_data or "data_type_id" in update_data:
            target_id = update_data.get("data_type_id", db_obj.data_type_id)
            target_type = await uow.data_types.get(target_id)
            if not target_type:
                raise AppException(errors.DATA_TYPE_NOT_FOUND)
            target_params = update_data.get("type_params", db_obj.type_params)
            validate_type_params(target_type.params_schema or {}, target_params)

    async def get_tree(self, uow: UnitOfWork, root_id: uuid.UUID) -> TypeInstanceTree:
        async with uow:
            repo = cast(TypeInstanceRepository, uow.type_instances)
            db_obj = await repo.get_tree(root_id)
            if not db_obj:
                raise AppException(errors.TYPE_INSTANCE_NOT_FOUND)
            return TypeInstanceTree.model_validate(db_obj)
