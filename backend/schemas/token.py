from pydantic import BaseModel


class Token(BaseModel):
    """Schema for the JWT access token response."""

    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class TokenData(BaseModel):
    """Schema for data encoded in the JWT."""

    user_id: str | None = None


class RefreshTokenRequest(BaseModel):
    """Schema for the refresh/logout endpoint request body."""

    refresh_token: str
