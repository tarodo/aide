import enum

from pydantic import BaseModel, ConfigDict, EmailStr

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class UserType(str, enum.Enum):
    REGULAR = "regular"
    TECHNICAL = "technical"


class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr
    full_name: str | None = None


class UserCreate(UserBase, NoteMixin):
    """Schema for user creation."""

    password: str
    user_type: UserType = UserType.REGULAR


class UserUpdate(VersionedUpdateMixin, NoteMixin):
    """Schema for user update."""

    email: EmailStr | None = None
    full_name: str | None = None
    user_type: UserType | None = None


class UserRead(UserBase, MetaDataMixin):
    """Schema for reading user data."""

    is_active: bool
    is_superuser: bool
    user_type: UserType

    model_config = ConfigDict(from_attributes=True)
