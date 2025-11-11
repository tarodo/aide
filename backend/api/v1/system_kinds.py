import uuid

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import (
    PaginationParams,
    get_current_superuser,
    get_pagination_params,
)
from backend.core.errors import (
    SYSTEM_KIND_ALREADY_EXISTS,
    SYSTEM_KIND_NOT_FOUND,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.pagination import Page
from backend.schemas.system_kind import (
    SystemKindCreate,
    SystemKindRead,
    SystemKindUpdate,
)
from backend.services.system_kind import SystemKindService

router = APIRouter()


@router.get(
    "/",
    response_model=Page[SystemKindRead],
    summary="Get all system kinds (paginated)",
    dependencies=[Depends(get_current_superuser)],
)
async def get_all_system_kinds(
    uow: UnitOfWork = Depends(UnitOfWork),
    system_kind_service: SystemKindService = Depends(SystemKindService),
    pagination: PaginationParams = Depends(get_pagination_params),
) -> Page[SystemKindRead]:
    """
    Get a paginated list of all system kinds. Requires superuser privileges.
    """
    return await system_kind_service.get_system_kinds_paginated(
        uow=uow, page=pagination.page, size=pagination.size
    )


@router.post(
    "/",
    response_model=SystemKindRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new system kind (admin only)",
    responses={
        **build_error_responses(SYSTEM_KIND_ALREADY_EXISTS),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def create_system_kind(
    system_kind_in: SystemKindCreate,
    uow: UnitOfWork = Depends(UnitOfWork),
    system_kind_service: SystemKindService = Depends(SystemKindService),
    current_superuser: User = Depends(get_current_superuser),
) -> SystemKindRead:
    """
    Create a new system kind. Requires superuser privileges.
    """
    creator_id = current_superuser.id
    return await system_kind_service.create_system_kind(
        uow=uow, system_kind_in=system_kind_in, creator_id=creator_id
    )


@router.get(
    "/{system_kind_id}",
    response_model=SystemKindRead,
    summary="Get a system kind by ID",
    responses={
        **build_error_responses(SYSTEM_KIND_NOT_FOUND),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def get_system_kind(
    system_kind_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
    system_kind_service: SystemKindService = Depends(SystemKindService),
    _current_user: User = Depends(get_current_superuser),
) -> SystemKindRead:
    """
    Get a system kind by its ID. Requires superuser privileges.
    """
    return await system_kind_service.get_system_kind(
        uow=uow, system_kind_id=system_kind_id
    )


@router.put(
    "/{system_kind_id}",
    response_model=SystemKindRead,
    summary="Update a system kind",
    responses={
        **build_error_responses(SYSTEM_KIND_NOT_FOUND, SYSTEM_KIND_ALREADY_EXISTS),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def update_system_kind(
    system_kind_id: uuid.UUID,
    system_kind_in: SystemKindUpdate,
    uow: UnitOfWork = Depends(UnitOfWork),
    system_kind_service: SystemKindService = Depends(SystemKindService),
    current_superuser: User = Depends(get_current_superuser),
) -> SystemKindRead:
    """
    Update a system kind. Requires superuser privileges.
    """
    updater_id = current_superuser.id
    return await system_kind_service.update_system_kind(
        uow=uow,
        system_kind_id=system_kind_id,
        system_kind_in=system_kind_in,
        updater_id=updater_id,
    )


@router.delete(
    "/{system_kind_id}",
    response_model=SystemKindRead,
    summary="Delete a system kind",
    responses={
        **build_error_responses(SYSTEM_KIND_NOT_FOUND),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def delete_system_kind(
    system_kind_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
    system_kind_service: SystemKindService = Depends(SystemKindService),
    _current_user: User = Depends(get_current_superuser),
) -> SystemKindRead:
    """
    Delete a system kind. Requires superuser privileges.
    """
    return await system_kind_service.delete_system_kind(
        uow=uow, system_kind_id=system_kind_id
    )
