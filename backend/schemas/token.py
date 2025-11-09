from pydantic import BaseModel


class Token(BaseModel):
    """Schema for the JWT access token response."""

    access_token: str
    token_type: str


class TokenData(BaseModel):
    """Schema for data encoded in the JWT."""

    user_id: str | None = None
