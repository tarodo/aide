from backend.core import errors
from backend.core.exceptions import AppException
from backend.core.security import verify_password
from backend.db.uow import UnitOfWork
from backend.models import User


class AuthService:
    """
    Service for user authentication.
    """

    async def authenticate_user(
        self, uow: UnitOfWork, *, email: str, password: str
    ) -> User:
        """
        Authenticate a user by email and password.

        :return: The authenticated user model.
        :raises InvalidCredentialsError: If authentication fails.
        """
        async with uow:
            user = await uow.users.get_by_email(email=email)
            if not user or not verify_password(password, user.hashed_password):
                raise AppException(errors.INVALID_CREDENTIALS)
            # Access id while session is still open to prevent DetachedInstanceError
            _ = user.id
            # Expunge the object from session so it can be used after session closes
            uow.session.expunge(user)
            return user
