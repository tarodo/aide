from fastapi import APIRouter

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    CREDENTIAL_REF_NOT_FOUND,
    ENTITY_NOT_DELETED,
    HAS_DEPENDENT_ENTITIES,
    SYSTEM_ALREADY_EXISTS,
    SYSTEM_FLAVOR_NOT_FOUND,
    SYSTEM_NOT_FOUND,
)
from backend.schemas.filters import SYSTEM_SORTABLE, SystemFilter
from backend.schemas.system import (
    SystemCreate,
    SystemRead,
    SystemUpdate,
)
from backend.services.system import SystemService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=SystemService,
    create_schema=SystemCreate,
    update_schema=SystemUpdate,
    read_schema=SystemRead,
    entity_name="system",
    create_error_codes=[
        SYSTEM_ALREADY_EXISTS,
        SYSTEM_FLAVOR_NOT_FOUND,
        CREDENTIAL_REF_NOT_FOUND,
    ],
    update_error_codes=[
        SYSTEM_NOT_FOUND,
        SYSTEM_ALREADY_EXISTS,
        SYSTEM_FLAVOR_NOT_FOUND,
        CREDENTIAL_REF_NOT_FOUND,
    ],
    get_one_error_codes=[SYSTEM_NOT_FOUND],
    delete_error_codes=[SYSTEM_NOT_FOUND, HAS_DEPENDENT_ENTITIES],
    supports_restore=True,
    restore_error_codes=[SYSTEM_NOT_FOUND, ENTITY_NOT_DELETED],
    filter_model=SystemFilter,
    sortable_fields=SYSTEM_SORTABLE,
    default_sort="code",
)

router.include_router(crud_router)
