from fastapi import APIRouter

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    DATASET_SCHEMA_NOT_FOUND,
    DATA_TYPE_NOT_FOUND,
    FIELD_BINDING_FIELD_ID_ALREADY_EXISTS,
    FIELD_BINDING_NOT_FOUND,
    FIELD_BINDING_POSITION_ALREADY_EXISTS,
    FIELD_NOT_FOUND,
)
from backend.schemas.field_binding import (
    FieldBindingCreate,
    FieldBindingRead,
    FieldBindingUpdate,
)
from backend.services.field_binding import FieldBindingService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=FieldBindingService,
    create_schema=FieldBindingCreate,
    update_schema=FieldBindingUpdate,
    read_schema=FieldBindingRead,
    entity_name="field binding",
    create_error_codes=[
        FIELD_BINDING_FIELD_ID_ALREADY_EXISTS,
        FIELD_BINDING_POSITION_ALREADY_EXISTS,
        FIELD_NOT_FOUND,
        DATASET_SCHEMA_NOT_FOUND,
        DATA_TYPE_NOT_FOUND,
    ],
    update_error_codes=[
        FIELD_BINDING_NOT_FOUND,
        FIELD_BINDING_FIELD_ID_ALREADY_EXISTS,
        FIELD_BINDING_POSITION_ALREADY_EXISTS,
        FIELD_NOT_FOUND,
        DATASET_SCHEMA_NOT_FOUND,
        DATA_TYPE_NOT_FOUND,
    ],
    get_one_error_codes=[FIELD_BINDING_NOT_FOUND],
    delete_error_codes=[FIELD_BINDING_NOT_FOUND],
)

router.include_router(crud_router)
