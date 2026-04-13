from fastapi import APIRouter

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    DATA_TYPE_ALREADY_EXISTS,
    DATA_TYPE_NOT_FOUND,
    ENTITY_NOT_DELETED,
    SYSTEM_FLAVOR_NOT_FOUND,
    VERSION_CONFLICT,
)
from backend.schemas.data_type import (
    DataTypeCreate,
    DataTypeRead,
    DataTypeUpdate,
)
from backend.schemas.filters import DATA_TYPE_SORTABLE, DataTypeFilter
from backend.services.data_type import DataTypeService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=DataTypeService,
    create_schema=DataTypeCreate,
    update_schema=DataTypeUpdate,
    read_schema=DataTypeRead,
    entity_name="data type",
    create_error_codes=[DATA_TYPE_ALREADY_EXISTS, SYSTEM_FLAVOR_NOT_FOUND],
    update_error_codes=[
        DATA_TYPE_NOT_FOUND,
        DATA_TYPE_ALREADY_EXISTS,
        SYSTEM_FLAVOR_NOT_FOUND,
        VERSION_CONFLICT,
    ],
    get_one_error_codes=[DATA_TYPE_NOT_FOUND],
    delete_error_codes=[DATA_TYPE_NOT_FOUND],
    supports_restore=True,
    restore_error_codes=[DATA_TYPE_NOT_FOUND, ENTITY_NOT_DELETED],
    filter_model=DataTypeFilter,
    sortable_fields=DATA_TYPE_SORTABLE,
    default_sort="code",
)

router.include_router(crud_router)
