import uuid
from datetime import datetime, timedelta, timezone

from backend.core import errors
from backend.core.exceptions import AppException
from backend.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    verify_password,
)
from backend.core.settings import settings
from backend.db.uow import UnitOfWork
from backend.models import RefreshToken, User
from backend.models.user import UserType
from backend.schemas.token import Token


class AuthService:
    """
    Service for user authentication and token management.
    """

    async def authenticate_user(
        self, uow: UnitOfWork, *, email: str, password: str
    ) -> User:
        """
        Authenticate a user by email and password.

        The caller must provide a UoW that is already in an active context
        (i.e. inside ``async with uow:``).

        :return: The authenticated user model.
        :raises AppException: If authentication fails.
        """
        user = await uow.users.get_by_email(email=email)
        if not user or not verify_password(password, user.hashed_password):
            raise AppException(errors.INVALID_CREDENTIALS)
        return user

    async def create_tokens_for_user(
        self,
        uow: UnitOfWork,
        user: User,
        *,
        client_info: str | None = None,
    ) -> Token:
        """Create an access + refresh token pair for a user."""
        access_token = create_access_token(data={"user_id": str(user.id)})

        raw_token, token_hash = generate_refresh_token()

        if user.user_type == UserType.TECHNICAL.value:
            expire_days = settings.REFRESH_TOKEN_EXPIRE_DAYS_TECHNICAL
        else:
            expire_days = settings.REFRESH_TOKEN_EXPIRE_DAYS

        expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)

        db_token = RefreshToken(
            token_hash=token_hash,
            user_id=user.id,
            expires_at=expires_at,
            client_info=client_info,
        )
        await uow.refresh_tokens.create(obj_in=db_token)

        return Token(
            access_token=access_token,
            refresh_token=raw_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh_access_token(
        self,
        uow: UnitOfWork,
        *,
        raw_refresh_token: str,
        client_info: str | None = None,
    ) -> Token:
        """Validate a refresh token, rotate it, and return a new token pair."""
        token_hash = hash_refresh_token(raw_refresh_token)
        db_token = await uow.refresh_tokens.get_by_token_hash(token_hash)

        if not db_token:
            raise AppException(errors.REFRESH_TOKEN_INVALID)

        if db_token.revoked_at is not None:
            raise AppException(errors.REFRESH_TOKEN_REVOKED)

        if db_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(
            timezone.utc
        ):
            raise AppException(errors.REFRESH_TOKEN_EXPIRED)

        # Revoke old token (rotation)
        db_token.revoked_at = datetime.now(timezone.utc)
        await uow.refresh_tokens.update(db_obj=db_token)

        # Verify user is still active
        user = await uow.users.get(db_token.user_id)
        if not user or not user.is_active:
            raise AppException(errors.INVALID_CREDENTIALS)

        return await self.create_tokens_for_user(uow, user, client_info=client_info)

    async def revoke_refresh_token(
        self, uow: UnitOfWork, *, raw_refresh_token: str
    ) -> None:
        """Revoke a single refresh token (logout)."""
        token_hash = hash_refresh_token(raw_refresh_token)
        db_token = await uow.refresh_tokens.get_by_token_hash(token_hash)

        if db_token and db_token.revoked_at is None:
            db_token.revoked_at = datetime.now(timezone.utc)
            await uow.refresh_tokens.update(db_obj=db_token)

    async def revoke_all_user_tokens(
        self, uow: UnitOfWork, *, user_id: uuid.UUID
    ) -> None:
        """Revoke all refresh tokens for a user (logout-all)."""
        await uow.refresh_tokens.revoke_all_for_user(user_id)
