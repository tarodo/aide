import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.schemas.mixins import MetaDataMixin, NoteMixin


class DataTypeBase(BaseModel):
    """Base data type schema."""

    system_flavor_id: uuid.UUID
    code: str
    params_schema: dict[str, Any]
    render_template: str | None = None


class DataTypeCreate(DataTypeBase, NoteMixin):
    """Schema for data type creation."""

    pass


class DataTypeUpdate(NoteMixin):
    """Schema for data type update."""

    system_flavor_id: uuid.UUID | None = None
    code: str | None = None
    params_schema: dict[str, Any] | None = None
    render_template: str | None = None


class DataTypeRead(DataTypeBase, MetaDataMixin):
    """Schema for reading data type data."""

    model_config = ConfigDict(from_attributes=True)
