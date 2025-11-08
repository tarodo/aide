import uuid

from fastapi import HTTPException, status

from backend.core.security import get_password_hash
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.user import UserCreate, UserRead


class UserService:
    """
    Service for user-related business logic.
    """

    async def create_user(self, uow: UnitOfWork, user_in: UserCreate) -> UserRead:
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

            db_user = await uow.users.create(obj_in=db_user)
            # Convert to Pydantic schema while session is still active
            return UserRead.model_validate(db_user)

    async def get_user(self, uow: UnitOfWork, user_id: uuid.UUID) -> UserRead | None:
        """
        Get a user by ID.
        """
        async with uow:
            db_user = await uow.users.get(user_id)
            if db_user:
                # Convert to Pydantic schema while session is still active
                return UserRead.model_validate(db_user)
            return None
