from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class SystemKindBase(BaseModel):
    """Base system kind schema."""

    code: str
    name: str


class SystemKindCreate(SystemKindBase, NoteMixin):
    """Schema for system kind creation."""

    pass


class SystemKindUpdate(VersionedUpdateMixin, NoteMixin):
    """Schema for system kind update."""

    code: str | None = None
    name: str | None = None


class SystemKindRead(SystemKindBase, MetaDataMixin):
    """Schema for reading system kind data."""

    model_config = ConfigDict(from_attributes=True)
