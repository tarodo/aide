import uuid

from pydantic import BaseModel, ConfigDict

from backend.schemas.mixins import MetaDataMixin, NoteMixin


class SystemFlavorBase(BaseModel):
    """Base system flavor schema."""

    code: str
    name: str
    vendor: str | None = None
    versions: list[str] | None = None
    kind_id: uuid.UUID


class SystemFlavorCreate(SystemFlavorBase, NoteMixin):
    """Schema for system flavor creation."""

    pass


class SystemFlavorUpdate(NoteMixin):
    """Schema for system flavor update."""

    code: str | None = None
    name: str | None = None
    vendor: str | None = None
    versions: list[str] | None = None
    kind_id: uuid.UUID | None = None


class SystemFlavorRead(SystemFlavorBase, MetaDataMixin):
    """Schema for reading system flavor data."""

    model_config = ConfigDict(from_attributes=True)
