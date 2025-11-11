import uuid

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import (
    PaginationParams,
    get_current_superuser,
    get_pagination_params,
)
from backend.core.errors import (
    DATA_TYPE_ALREADY_EXISTS,
    DATA_TYPE_NOT_FOUND,
    SYSTEM_FLAVOR_NOT_FOUND,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.data_type import (
    DataTypeCreate,
    DataTypeRead,
    DataTypeUpdate,
)
from backend.schemas.pagination import Page
from backend.services.data_type import DataTypeService

router = APIRouter()


@router.get(
    "/",
    response_model=Page[DataTypeRead],
    summary="Get all data types (paginated)",
    dependencies=[Depends(get_current_superuser)],
)
async def get_all_data_types(
    uow: UnitOfWork = Depends(UnitOfWork),
    data_type_service: DataTypeService = Depends(DataTypeService),
    pagination: PaginationParams = Depends(get_pagination_params),
) -> Page[DataTypeRead]:
    """
    Get a paginated list of all data types. Requires superuser privileges.
    """
    return await data_type_service.get_data_types_paginated(
        uow=uow, page=pagination.page, size=pagination.size
    )


@router.post(
    "/",
    response_model=DataTypeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new data type (admin only)",
    responses={
        **build_error_responses(DATA_TYPE_ALREADY_EXISTS, SYSTEM_FLAVOR_NOT_FOUND),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def create_data_type(
    data_type_in: DataTypeCreate,
    uow: UnitOfWork = Depends(UnitOfWork),
    data_type_service: DataTypeService = Depends(DataTypeService),
    current_superuser: User = Depends(get_current_superuser),
) -> DataTypeRead:
    """
    Create a new data type. Requires superuser privileges.
    """
    creator_id = current_superuser.id
    return await data_type_service.create_data_type(
        uow=uow, data_type_in=data_type_in, creator_id=creator_id
    )


@router.get(
    "/{data_type_id}",
    response_model=DataTypeRead,
    summary="Get a data type by ID",
    responses={
        **build_error_responses(DATA_TYPE_NOT_FOUND),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def get_data_type(
    data_type_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
    data_type_service: DataTypeService = Depends(DataTypeService),
    _current_user: User = Depends(get_current_superuser),
) -> DataTypeRead:
    """
    Get a data type by its ID. Requires superuser privileges.
    """
    return await data_type_service.get_data_type(uow=uow, data_type_id=data_type_id)


@router.put(
    "/{data_type_id}",
    response_model=DataTypeRead,
    summary="Update a data type",
    responses={
        **build_error_responses(
            DATA_TYPE_NOT_FOUND,
            DATA_TYPE_ALREADY_EXISTS,
            SYSTEM_FLAVOR_NOT_FOUND,
        ),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def update_data_type(
    data_type_id: uuid.UUID,
    data_type_in: DataTypeUpdate,
    uow: UnitOfWork = Depends(UnitOfWork),
    data_type_service: DataTypeService = Depends(DataTypeService),
    current_superuser: User = Depends(get_current_superuser),
) -> DataTypeRead:
    """
    Update a data type. Requires superuser privileges.
    """
    updater_id = current_superuser.id
    return await data_type_service.update_data_type(
        uow=uow,
        data_type_id=data_type_id,
        data_type_in=data_type_in,
        updater_id=updater_id,
    )


@router.delete(
    "/{data_type_id}",
    response_model=DataTypeRead,
    summary="Delete a data type",
    responses={
        **build_error_responses(DATA_TYPE_NOT_FOUND),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def delete_data_type(
    data_type_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
    data_type_service: DataTypeService = Depends(DataTypeService),
    _current_user: User = Depends(get_current_superuser),
) -> DataTypeRead:
    """
    Delete a data type. Requires superuser privileges.
    """
    return await data_type_service.delete_data_type(uow=uow, data_type_id=data_type_id)
