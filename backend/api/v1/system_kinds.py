from fastapi import APIRouter

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    ENTITY_NOT_DELETED,
    HAS_DEPENDENT_ENTITIES,
    SYSTEM_KIND_ALREADY_EXISTS,
    SYSTEM_KIND_NOT_FOUND,
    VERSION_CONFLICT,
)
from backend.schemas.filters import SYSTEM_KIND_SORTABLE, SystemKindFilter
from backend.schemas.system_kind import (
    SystemKindCreate,
    SystemKindRead,
    SystemKindUpdate,
)
from backend.services.system_kind import SystemKindService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=SystemKindService,
    create_schema=SystemKindCreate,
    update_schema=SystemKindUpdate,
    read_schema=SystemKindRead,
    entity_name="system kind",
    create_error_codes=[SYSTEM_KIND_ALREADY_EXISTS],
    update_error_codes=[
        SYSTEM_KIND_NOT_FOUND,
        SYSTEM_KIND_ALREADY_EXISTS,
        VERSION_CONFLICT,
    ],
    get_one_error_codes=[SYSTEM_KIND_NOT_FOUND],
    delete_error_codes=[SYSTEM_KIND_NOT_FOUND, HAS_DEPENDENT_ENTITIES],
    supports_restore=True,
    restore_error_codes=[SYSTEM_KIND_NOT_FOUND, ENTITY_NOT_DELETED],
    filter_model=SystemKindFilter,
    sortable_fields=SYSTEM_KIND_SORTABLE,
    default_sort="code",
)

router.include_router(crud_router)
