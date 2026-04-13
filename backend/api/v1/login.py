from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from backend.api.dependencies import get_current_user
from backend.core.errors import build_error_responses
from backend.core import errors
from backend.core.rate_limit import limiter
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.error import ErrorResponse
from backend.schemas.token import RefreshTokenRequest, Token
from backend.services.auth_service import AuthService

router = APIRouter()


@router.post(
    "/",
    response_model=Token,
    summary="Login for access token",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Incorrect email or password.",
        }
    },
)
@limiter.limit("5/minute")
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    uow: UnitOfWork = Depends(UnitOfWork),
    auth_service: AuthService = Depends(AuthService),
) -> Token:
    """
    OAuth2 compatible token login, get an access token and refresh token.
    """
    async with uow:
        user = await auth_service.authenticate_user(
            uow=uow, email=form_data.username, password=form_data.password
        )
        return await auth_service.create_tokens_for_user(
            uow,
            user,
            client_info=request.headers.get("User-Agent"),
        )


@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh access token",
    responses=build_error_responses(
        errors.REFRESH_TOKEN_INVALID,
        errors.REFRESH_TOKEN_EXPIRED,
        errors.REFRESH_TOKEN_REVOKED,
    ),
)
@limiter.limit("10/minute")
async def refresh_token(
    request: Request,
    body: RefreshTokenRequest,
    uow: UnitOfWork = Depends(UnitOfWork),
    auth_service: AuthService = Depends(AuthService),
) -> Token:
    """
    Get a new access token using a valid refresh token.
    The old refresh token is revoked and a new one is issued (rotation).
    """
    async with uow:
        return await auth_service.refresh_access_token(
            uow,
            raw_refresh_token=body.refresh_token,
            client_info=request.headers.get("User-Agent"),
        )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout (revoke refresh token)",
)
async def logout(
    body: RefreshTokenRequest,
    uow: UnitOfWork = Depends(UnitOfWork),
    auth_service: AuthService = Depends(AuthService),
) -> None:
    """Revoke a single refresh token."""
    async with uow:
        await auth_service.revoke_refresh_token(
            uow, raw_refresh_token=body.refresh_token
        )


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout from all sessions",
)
async def logout_all(
    current_user: Annotated[User, Depends(get_current_user)],
    uow: UnitOfWork = Depends(UnitOfWork),
    auth_service: AuthService = Depends(AuthService),
) -> None:
    """Revoke all refresh tokens for the current user."""
    async with uow:
        await auth_service.revoke_all_user_tokens(uow, user_id=current_user.id)
