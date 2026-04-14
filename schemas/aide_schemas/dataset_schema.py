import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class DatasetSchemaBase(BaseModel):
    """Base dataset schema."""

    dataset_id: uuid.UUID
    version_num: int
    schema_: dict[str, Any] | None = Field(
        None, alias="schema", serialization_alias="schema_"
    )
    extra: dict[str, Any] | None = None


class DatasetSchemaCreate(DatasetSchemaBase, NoteMixin):
    """Schema for dataset schema creation."""

    pass


class DatasetSchemaUpdate(VersionedUpdateMixin, NoteMixin):
    """Schema for dataset schema update."""

    dataset_id: uuid.UUID | None = None
    version_num: int | None = None
    schema_: dict[str, Any] | None = Field(
        None, alias="schema", serialization_alias="schema_"
    )
    extra: dict[str, Any] | None = None


class DatasetSchemaRead(DatasetSchemaBase, MetaDataMixin):
    """Schema for reading dataset schema data."""

    model_config = ConfigDict(from_attributes=True)
