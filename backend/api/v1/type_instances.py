import uuid

from fastapi import APIRouter, Depends

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    DATA_TYPE_NOT_FOUND,
    TYPE_INSTANCE_NOT_FOUND,
    TYPE_INSTANCE_PARENT_NOT_FOUND,
    TYPE_INSTANCE_SLOT_ALREADY_EXISTS,
    TYPE_INSTANCE_SLOT_FORBIDDEN,
    TYPE_INSTANCE_SLOT_REQUIRED,
    UNAUTHORIZED,
    FORBIDDEN,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.schemas.filters import TYPE_INSTANCE_SORTABLE, TypeInstanceFilter
from backend.schemas.type_instance import (
    TypeInstanceCreate,
    TypeInstanceRead,
    TypeInstanceTree,
    TypeInstanceUpdate,
)
from backend.services.type_instance import TypeInstanceService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=TypeInstanceService,
    create_schema=TypeInstanceCreate,
    update_schema=TypeInstanceUpdate,
    read_schema=TypeInstanceRead,
    entity_name="type instance",
    create_error_codes=[
        DATA_TYPE_NOT_FOUND,
        TYPE_INSTANCE_PARENT_NOT_FOUND,
        TYPE_INSTANCE_SLOT_REQUIRED,
        TYPE_INSTANCE_SLOT_FORBIDDEN,
        TYPE_INSTANCE_SLOT_ALREADY_EXISTS,
    ],
    update_error_codes=[
        TYPE_INSTANCE_NOT_FOUND,
        DATA_TYPE_NOT_FOUND,
        VERSION_CONFLICT,
    ],
    get_one_error_codes=[TYPE_INSTANCE_NOT_FOUND],
    delete_error_codes=[TYPE_INSTANCE_NOT_FOUND],
    filter_model=TypeInstanceFilter,
    sortable_fields=TYPE_INSTANCE_SORTABLE,
    supports_batch=True,
)

router.include_router(crud_router)


@router.get(
    "/{obj_id}/tree",
    response_model=TypeInstanceTree,
    summary="Get a type instance tree by root ID",
    responses={
        **build_error_responses(TYPE_INSTANCE_NOT_FOUND, UNAUTHORIZED, FORBIDDEN),
    },
)
async def get_tree(
    obj_id: uuid.UUID,
    service: TypeInstanceService = Depends(TypeInstanceService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> TypeInstanceTree:
    return await service.get_tree(uow=uow, root_id=obj_id)
