import uuid

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_current_user, get_current_superuser
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.error import ErrorResponse
from backend.schemas.user import UserCreate, UserRead
from backend.services.user import UserService

router = APIRouter()


@router.post(
    "/",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (admin only)",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "User with this email already exists.",
        },
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
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The requested user was not found.",
        },
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
