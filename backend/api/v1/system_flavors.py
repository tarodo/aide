import uuid

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import (
    PaginationParams,
    get_current_superuser,
    get_pagination_params,
)
from backend.core.errors import (
    SYSTEM_FLAVOR_ALREADY_EXISTS,
    SYSTEM_FLAVOR_NOT_FOUND,
    SYSTEM_KIND_NOT_FOUND,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.pagination import Page
from backend.schemas.system_flavor import (
    SystemFlavorCreate,
    SystemFlavorRead,
    SystemFlavorUpdate,
)
from backend.services.system_flavor import SystemFlavorService

router = APIRouter()


@router.get(
    "/",
    response_model=Page[SystemFlavorRead],
    summary="Get all system flavors (paginated)",
    dependencies=[Depends(get_current_superuser)],
)
async def get_all_system_flavors(
    uow: UnitOfWork = Depends(UnitOfWork),
    system_flavor_service: SystemFlavorService = Depends(SystemFlavorService),
    pagination: PaginationParams = Depends(get_pagination_params),
) -> Page[SystemFlavorRead]:
    """
    Get a paginated list of all system flavors. Requires superuser privileges.
    """
    return await system_flavor_service.get_system_flavors_paginated(
        uow=uow, page=pagination.page, size=pagination.size
    )


@router.post(
    "/",
    response_model=SystemFlavorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new system flavor (admin only)",
    responses={
        **build_error_responses(SYSTEM_FLAVOR_ALREADY_EXISTS, SYSTEM_KIND_NOT_FOUND),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def create_system_flavor(
    system_flavor_in: SystemFlavorCreate,
    uow: UnitOfWork = Depends(UnitOfWork),
    system_flavor_service: SystemFlavorService = Depends(SystemFlavorService),
    current_superuser: User = Depends(get_current_superuser),
) -> SystemFlavorRead:
    """
    Create a new system flavor. Requires superuser privileges.
    """
    creator_id = current_superuser.id
    return await system_flavor_service.create_system_flavor(
        uow=uow, system_flavor_in=system_flavor_in, creator_id=creator_id
    )


@router.get(
    "/{system_flavor_id}",
    response_model=SystemFlavorRead,
    summary="Get a system flavor by ID",
    responses={
        **build_error_responses(SYSTEM_FLAVOR_NOT_FOUND),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def get_system_flavor(
    system_flavor_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
    system_flavor_service: SystemFlavorService = Depends(SystemFlavorService),
    _current_user: User = Depends(get_current_superuser),
) -> SystemFlavorRead:
    """
    Get a system flavor by its ID. Requires superuser privileges.
    """
    return await system_flavor_service.get_system_flavor(
        uow=uow, system_flavor_id=system_flavor_id
    )


@router.put(
    "/{system_flavor_id}",
    response_model=SystemFlavorRead,
    summary="Update a system flavor",
    responses={
        **build_error_responses(
            SYSTEM_FLAVOR_NOT_FOUND,
            SYSTEM_FLAVOR_ALREADY_EXISTS,
            SYSTEM_KIND_NOT_FOUND,
        ),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def update_system_flavor(
    system_flavor_id: uuid.UUID,
    system_flavor_in: SystemFlavorUpdate,
    uow: UnitOfWork = Depends(UnitOfWork),
    system_flavor_service: SystemFlavorService = Depends(SystemFlavorService),
    current_superuser: User = Depends(get_current_superuser),
) -> SystemFlavorRead:
    """
    Update a system flavor. Requires superuser privileges.
    """
    updater_id = current_superuser.id
    return await system_flavor_service.update_system_flavor(
        uow=uow,
        system_flavor_id=system_flavor_id,
        system_flavor_in=system_flavor_in,
        updater_id=updater_id,
    )


@router.delete(
    "/{system_flavor_id}",
    response_model=SystemFlavorRead,
    summary="Delete a system flavor",
    responses={
        **build_error_responses(SYSTEM_FLAVOR_NOT_FOUND),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def delete_system_flavor(
    system_flavor_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
    system_flavor_service: SystemFlavorService = Depends(SystemFlavorService),
    _current_user: User = Depends(get_current_superuser),
) -> SystemFlavorRead:
    """
    Delete a system flavor. Requires superuser privileges.
    """
    return await system_flavor_service.delete_system_flavor(
        uow=uow, system_flavor_id=system_flavor_id
    )
