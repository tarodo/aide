import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class SystemBase(BaseModel):
    """Base system schema."""

    code: str
    name: str
    flavor_id: uuid.UUID
    credential_ref_id: uuid.UUID | None = None
    is_active: bool = True
    tags: list[str] | None = None
    extra: dict[str, Any] | None = None


class SystemCreate(SystemBase, NoteMixin):
    """Schema for system creation."""

    pass


class SystemUpdate(VersionedUpdateMixin, NoteMixin):
    """Schema for system update."""

    code: str | None = None
    name: str | None = None
    flavor_id: uuid.UUID | None = None
    credential_ref_id: uuid.UUID | None = None
    is_active: bool | None = None
    tags: list[str] | None = None
    extra: dict[str, Any] | None = None


class SystemRead(SystemBase, MetaDataMixin):
    """Schema for reading system data."""

    model_config = ConfigDict(from_attributes=True)
