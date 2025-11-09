from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from backend.core.security import create_access_token
from backend.db.uow import UnitOfWork
from backend.schemas.token import Token
from backend.services.auth_service import AuthService
from backend.services.exceptions import InvalidCredentialsError

router = APIRouter()


@router.post("/", response_model=Token, summary="Login for access token")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    uow: UnitOfWork = Depends(UnitOfWork),
    auth_service: AuthService = Depends(AuthService),
) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    try:
        user = await auth_service.authenticate_user(
            uow=uow, email=form_data.username, password=form_data.password
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"user_id": str(user.id)})
    return Token(access_token=access_token, token_type="bearer")
