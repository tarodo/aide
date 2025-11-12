from fastapi import APIRouter

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    SYSTEM_FLAVOR_ALREADY_EXISTS,
    SYSTEM_FLAVOR_NOT_FOUND,
    SYSTEM_KIND_NOT_FOUND,
)
from backend.schemas.system_flavor import (
    SystemFlavorCreate,
    SystemFlavorRead,
    SystemFlavorUpdate,
)
from backend.services.system_flavor import SystemFlavorService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=SystemFlavorService,
    create_schema=SystemFlavorCreate,
    update_schema=SystemFlavorUpdate,
    read_schema=SystemFlavorRead,
    entity_name="system flavor",
    create_error_codes=[SYSTEM_FLAVOR_ALREADY_EXISTS, SYSTEM_KIND_NOT_FOUND],
    update_error_codes=[
        SYSTEM_FLAVOR_NOT_FOUND,
        SYSTEM_FLAVOR_ALREADY_EXISTS,
        SYSTEM_KIND_NOT_FOUND,
    ],
    get_one_error_codes=[SYSTEM_FLAVOR_NOT_FOUND],
    delete_error_codes=[SYSTEM_FLAVOR_NOT_FOUND],
)

router.include_router(crud_router)
