import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from backend.core.security import decode_access_token
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.token import TokenData

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")


@dataclass(frozen=True)
class PaginationParams:
    page: int
    size: int


def get_pagination_params(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=100, description="Page size"),
) -> PaginationParams:
    """
    Dependency to parse and validate pagination query parameters.
    """
    return PaginationParams(page=page, size=size)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    uow: Annotated[UnitOfWork, Depends(UnitOfWork)],
) -> User:
    """
    Decode JWT token to get user ID, then retrieve user from database.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        token_data = TokenData(user_id=payload.get("user_id"))
    except (JWTError, ValueError):
        raise credentials_exception

    if token_data.user_id is None:
        raise credentials_exception

    async with uow:
        user = await uow.users.get(uuid.UUID(token_data.user_id))
        if user is None or not user.is_active:
            raise credentials_exception
        # Access attributes while session is active to prevent DetachedInstanceError
        _ = user.is_superuser
        # Expunge to detach from session, making attributes accessible after session closes
        session = getattr(uow, "session", None)
        if session is not None:
            session.expunge(user)
        return user


async def get_current_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Check if the current user is a superuser.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges",
        )
    return current_user
