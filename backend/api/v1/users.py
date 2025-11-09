import uuid

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_current_user, get_current_superuser
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.user import UserCreate, UserRead
from backend.services.user import UserService

router = APIRouter()


@router.post(
    "/",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (admin only)",
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


@router.get("/me", response_model=UserRead, summary="Get current user")
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
