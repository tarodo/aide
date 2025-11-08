import uuid

from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr
    full_name: str | None = None


class UserCreate(UserBase):
    """Schema for user creation."""

    password: str


class UserUpdate(BaseModel):
    """Schema for user update."""

    email: EmailStr | None = None
    full_name: str | None = None


class UserRead(UserBase):
    """Schema for reading user data."""

    id: uuid.UUID
    is_active: bool
    is_superuser: bool

    model_config = ConfigDict(from_attributes=True)
