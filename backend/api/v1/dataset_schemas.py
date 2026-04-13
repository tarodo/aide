from fastapi import APIRouter

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    DATASET_NOT_FOUND,
    DATASET_SCHEMA_ALREADY_EXISTS,
    DATASET_SCHEMA_NOT_FOUND,
    VERSION_CONFLICT,
)
from backend.schemas.dataset_schema import (
    DatasetSchemaCreate,
    DatasetSchemaRead,
    DatasetSchemaUpdate,
)
from backend.schemas.filters import DATASET_SCHEMA_SORTABLE, DatasetSchemaFilter
from backend.services.dataset_schema import DatasetSchemaService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=DatasetSchemaService,
    create_schema=DatasetSchemaCreate,
    update_schema=DatasetSchemaUpdate,
    read_schema=DatasetSchemaRead,
    entity_name="dataset schema",
    create_error_codes=[DATASET_SCHEMA_ALREADY_EXISTS, DATASET_NOT_FOUND],
    update_error_codes=[
        DATASET_SCHEMA_NOT_FOUND,
        DATASET_SCHEMA_ALREADY_EXISTS,
        DATASET_NOT_FOUND,
        VERSION_CONFLICT,
    ],
    get_one_error_codes=[DATASET_SCHEMA_NOT_FOUND],
    delete_error_codes=[DATASET_SCHEMA_NOT_FOUND],
    filter_model=DatasetSchemaFilter,
    sortable_fields=DATASET_SCHEMA_SORTABLE,
)

router.include_router(crud_router)
