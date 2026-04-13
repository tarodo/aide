import uuid

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import (
    get_current_superuser,
    get_current_user,
)
from backend.api.filter_sort import FilterSortParams, get_filter_sort_dependency
from backend.core.errors import (
    FORBIDDEN,
    UNAUTHORIZED,
    USER_ALREADY_EXISTS,
    USER_NOT_FOUND,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.filters import USER_SORTABLE, UserFilter
from backend.schemas.pagination import Page
from backend.schemas.user import UserCreate, UserRead
from backend.services.user import UserService

router = APIRouter()

_filter_sort = get_filter_sort_dependency(UserFilter, USER_SORTABLE, "email")


@router.get(
    "/",
    response_model=Page[UserRead],
    summary="Get all users (paginated)",
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(UNAUTHORIZED, FORBIDDEN),
    },
)
async def get_all_users(
    uow: UnitOfWork = Depends(UnitOfWork),
    user_service: UserService = Depends(UserService),
    params: FilterSortParams = Depends(_filter_sort),
) -> Page[UserRead]:
    return await user_service.get_users_paginated(
        uow=uow,
        page=params.page,
        size=params.size,
        filters=params.filters,
        sort=params.sort,
    )


@router.post(
    "/",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (admin only)",
    responses={
        **build_error_responses(USER_ALREADY_EXISTS, UNAUTHORIZED, FORBIDDEN),
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
    responses={**build_error_responses(UNAUTHORIZED)},
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
        **build_error_responses(USER_NOT_FOUND, UNAUTHORIZED, FORBIDDEN),
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
