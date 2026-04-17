import uuid

from fastapi import APIRouter, Depends

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    FIELD_CLASSIFICATION_NOT_FOUND,
    FIELD_NOT_FOUND,
    FORBIDDEN,
    UNAUTHORIZED,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.schemas.field_classification import (
    FieldClassificationCreate,
    FieldClassificationRead,
)
from backend.schemas.filters import (
    FIELD_CLASSIFICATION_SORTABLE,
    FieldClassificationFilter,
)
from backend.services.field_classification import FieldClassificationService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=FieldClassificationService,
    create_schema=FieldClassificationCreate,
    update_schema=None,
    read_schema=FieldClassificationRead,
    entity_name="field classification",
    create_error_codes=[FIELD_NOT_FOUND],
    get_one_error_codes=[FIELD_CLASSIFICATION_NOT_FOUND],
    filter_model=FieldClassificationFilter,
    sortable_fields=FIELD_CLASSIFICATION_SORTABLE,
    default_sort="-created_at",
    supports_update=False,
    supports_delete=False,
)

router.include_router(crud_router)


@router.get(
    "/current/{field_id}",
    response_model=FieldClassificationRead,
    summary="Get the current classification for a field",
    responses={
        **build_error_responses(
            FIELD_CLASSIFICATION_NOT_FOUND, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def get_current_for_field(
    field_id: uuid.UUID,
    service: FieldClassificationService = Depends(FieldClassificationService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> FieldClassificationRead:
    return await service.get_current(uow=uow, field_id=field_id)


@router.get(
    "/by-dataset/{dataset_id}/current",
    response_model=list[FieldClassificationRead],
    summary="List current classifications for all fields in a dataset",
    responses={
        **build_error_responses(UNAUTHORIZED, FORBIDDEN),
    },
)
async def list_current_by_dataset(
    dataset_id: uuid.UUID,
    service: FieldClassificationService = Depends(FieldClassificationService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> list[FieldClassificationRead]:
    return await service.list_current_by_dataset(uow=uow, dataset_id=dataset_id)
