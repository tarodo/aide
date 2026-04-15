import uuid
from typing import List

from fastapi import APIRouter, Depends

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    DATASET_NOT_FOUND,
    FIELD_ALREADY_EXISTS,
    FIELD_CIRCULAR_REFERENCE,
    FIELD_NOT_FOUND,
    FIELD_PARENT_DATASET_MISMATCH,
    FIELD_PARENT_NOT_FOUND,
    FORBIDDEN,
    UNAUTHORIZED,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.schemas.field import (
    FieldCreate,
    FieldRead,
    FieldTree,
    FieldUpdate,
)
from backend.schemas.filters import FIELD_SORTABLE, FieldFilter
from backend.services.field import FieldService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=FieldService,
    create_schema=FieldCreate,
    update_schema=FieldUpdate,
    read_schema=FieldRead,
    entity_name="field",
    create_error_codes=[
        FIELD_ALREADY_EXISTS,
        DATASET_NOT_FOUND,
        FIELD_PARENT_NOT_FOUND,
        FIELD_PARENT_DATASET_MISMATCH,
    ],
    update_error_codes=[
        FIELD_NOT_FOUND,
        FIELD_ALREADY_EXISTS,
        DATASET_NOT_FOUND,
        FIELD_PARENT_NOT_FOUND,
        FIELD_PARENT_DATASET_MISMATCH,
        FIELD_CIRCULAR_REFERENCE,
        VERSION_CONFLICT,
    ],
    get_one_error_codes=[FIELD_NOT_FOUND],
    delete_error_codes=[FIELD_NOT_FOUND],
    filter_model=FieldFilter,
    sortable_fields=FIELD_SORTABLE,
    default_sort="name",
    supports_batch=True,
)

router.include_router(crud_router)


@router.get(
    "/tree/{dataset_id}",
    response_model=List[FieldTree],
    summary="Get the full field tree for a dataset",
    responses={
        **build_error_responses(DATASET_NOT_FOUND, UNAUTHORIZED, FORBIDDEN),
    },
)
async def get_field_tree(
    dataset_id: uuid.UUID,
    service: FieldService = Depends(FieldService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> List[FieldTree]:
    return await service.get_tree(uow=uow, dataset_id=dataset_id)


@router.get(
    "/{obj_id}/children",
    response_model=List[FieldRead],
    summary="Get direct children of a field",
    responses={
        **build_error_responses(FIELD_NOT_FOUND, UNAUTHORIZED, FORBIDDEN),
    },
)
async def get_field_children(
    obj_id: uuid.UUID,
    service: FieldService = Depends(FieldService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> List[FieldRead]:
    return await service.get_children(uow=uow, field_id=obj_id)
