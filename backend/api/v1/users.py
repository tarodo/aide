import uuid

from fastapi import APIRouter, Depends, status

from backend.db.uow import UnitOfWork
from backend.schemas.user import UserCreate, UserRead
from backend.services.user import UserService

router = APIRouter()


@router.post(
    "/",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
)
async def create_user(
    user_in: UserCreate,
    uow: UnitOfWork = Depends(UnitOfWork),
    user_service: UserService = Depends(UserService),
) -> UserRead:
    """
    Create a new user.
    """
    return await user_service.create_user(uow=uow, user_in=user_in)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Get a user by ID",
)
async def get_user(
    user_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
    user_service: UserService = Depends(UserService),
) -> UserRead:
    """
    Get a user by their ID.
    """
    return await user_service.get_user(uow=uow, user_id=user_id)
