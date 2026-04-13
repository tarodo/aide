import uuid

from pydantic import BaseModel, ConfigDict

from backend.schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class FieldBindingBase(BaseModel):
    """Base field binding schema."""

    field_id: uuid.UUID
    dataset_schema_id: uuid.UUID
    position: int
    is_nullable: bool = True
    type_instance_id: uuid.UUID


class FieldBindingCreate(FieldBindingBase, NoteMixin):
    """Schema for field binding creation."""

    pass


class FieldBindingUpdate(VersionedUpdateMixin, NoteMixin):
    """Schema for field binding update."""

    field_id: uuid.UUID | None = None
    dataset_schema_id: uuid.UUID | None = None
    position: int | None = None
    is_nullable: bool | None = None
    type_instance_id: uuid.UUID | None = None


class FieldBindingRead(FieldBindingBase, MetaDataMixin):
    """Schema for reading field binding data."""

    model_config = ConfigDict(from_attributes=True)
