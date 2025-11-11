import uuid

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import (
    PaginationParams,
    get_current_user,
    get_current_superuser,
    get_pagination_params,
)
from backend.core.errors import (
    USER_ALREADY_EXISTS,
    USER_NOT_FOUND,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.pagination import Page
from backend.schemas.user import UserCreate, UserRead
from backend.services.user import UserService

router = APIRouter()


@router.get(
    "/",
    response_model=Page[UserRead],
    summary="Get all users (paginated)",
    dependencies=[Depends(get_current_superuser)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def get_all_users(
    uow: UnitOfWork = Depends(UnitOfWork),
    user_service: UserService = Depends(UserService),
    pagination: PaginationParams = Depends(get_pagination_params),
) -> Page[UserRead]:
    """
    Get a paginated list of all users. Requires superuser privileges.
    """
    return await user_service.get_users_paginated(
        uow=uow, page=pagination.page, size=pagination.size
    )


@router.post(
    "/",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (admin only)",
    responses={
        **build_error_responses(USER_ALREADY_EXISTS),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def create_user(
    user_in: UserCreate,
    uow: UnitOfWork = Depends(UnitOfWork),
    user_service: UserService = Depends(UserService),
    current_superuser: User = Depends(get_current_superuser),
) -> UserRead:
    """
    Create a new user. Requires superuser privileges.
    """
    creator_id = current_superuser.id
    return await user_service.create_user(
        uow=uow, user_in=user_in, creator_id=creator_id
    )


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user",
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"}},
)
async def get_current_user_me(
    current_user: User = Depends(get_current_user),
) -> UserRead:
    """
    Get the current authenticated user's data.
    """
    return UserRead.model_validate(current_user)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Get a user by ID",
    responses={
        **build_error_responses(USER_NOT_FOUND),
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {
            "description": "The user doesn't have enough privileges"
        },
    },
)
async def get_user(
    user_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
    user_service: UserService = Depends(UserService),
    _current_user: User = Depends(get_current_superuser),
) -> UserRead:
    """
    Get a user by their ID. Requires superuser privileges.
    """
    return await user_service.get_user(uow=uow, user_id=user_id)
