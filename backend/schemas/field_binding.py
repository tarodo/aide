import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.schemas.mixins import MetaDataMixin, NoteMixin


class FieldBindingBase(BaseModel):
    """Base field binding schema."""

    field_id: uuid.UUID
    dataset_schema_id: uuid.UUID
    position: int
    is_nullable: bool = True
    data_type_id: uuid.UUID
    type_params: dict[str, Any] | None = None


class FieldBindingCreate(FieldBindingBase, NoteMixin):
    """Schema for field binding creation."""

    pass


class FieldBindingUpdate(NoteMixin):
    """Schema for field binding update."""

    field_id: uuid.UUID | None = None
    dataset_schema_id: uuid.UUID | None = None
    position: int | None = None
    is_nullable: bool | None = None
    data_type_id: uuid.UUID | None = None
    type_params: dict[str, Any] | None = None


class FieldBindingRead(FieldBindingBase, MetaDataMixin):
    """Schema for reading field binding data."""

    model_config = ConfigDict(from_attributes=True)
