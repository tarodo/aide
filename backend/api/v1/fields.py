from fastapi import APIRouter

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    DATASET_NOT_FOUND,
    DATA_TYPE_NOT_FOUND,
    FIELD_ALREADY_EXISTS,
    FIELD_NOT_FOUND,
)
from backend.schemas.field import (
    FieldCreate,
    FieldRead,
    FieldUpdate,
)
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
        DATA_TYPE_NOT_FOUND,
    ],
    update_error_codes=[
        FIELD_NOT_FOUND,
        FIELD_ALREADY_EXISTS,
        DATASET_NOT_FOUND,
        DATA_TYPE_NOT_FOUND,
    ],
    get_one_error_codes=[FIELD_NOT_FOUND],
    delete_error_codes=[FIELD_NOT_FOUND],
)

router.include_router(crud_router)
