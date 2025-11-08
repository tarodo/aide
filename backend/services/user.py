import uuid

from fastapi import HTTPException, status

from backend.core.security import get_password_hash
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.user import UserCreate


class UserService:
    """
    Service for user-related business logic.
    """

    async def create_user(self, uow: UnitOfWork, user_in: UserCreate) -> User:
        """
        Create a new user.
        """
        user_data = user_in.model_dump(exclude={"password"})
        hashed_password = get_password_hash(user_in.password)

        async with uow:
            if await uow.users.get_by_email(user_in.email):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The user with this email already exists in the system.",
                )

            db_user = User(**user_data, hashed_password=hashed_password)
            db_user.created_by = db_user.id
            db_user.updated_by = db_user.id

            return await uow.users.create(obj_in=db_user)

    async def get_user(self, uow: UnitOfWork, user_id: uuid.UUID) -> User | None:
        """
        Get a user by ID.
        """
        async with uow:
            return await uow.users.get(user_id)
