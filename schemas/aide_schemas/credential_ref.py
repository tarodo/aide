from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class CredentialRefBase(BaseModel):
    """Base credential ref schema."""

    provider: str
    path: str
    version: int | None = None


class CredentialRefCreate(CredentialRefBase, NoteMixin):
    """Schema for credential ref creation."""

    pass


class CredentialRefUpdate(VersionedUpdateMixin, NoteMixin):
    """Schema for credential ref update."""

    provider: str | None = None
    path: str | None = None
    version: int | None = None


class CredentialRefRead(CredentialRefBase, MetaDataMixin):
    """Schema for reading credential ref data."""

    model_config = ConfigDict(from_attributes=True)
