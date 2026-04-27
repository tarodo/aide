import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aide_schemas.tech_field_template import TechFieldOverride


class FieldOverride(BaseModel):
    """Per-field override of the resolved target type."""

    model_config = ConfigDict(extra="forbid")

    data_type_code: str
    type_params: dict[str, Any] | None = None


class LakeSyncRequest(BaseModel):
    """Body for POST /api/v1/datasets/{source_dataset_id}/lake-sync."""

    model_config = ConfigDict(extra="forbid")

    target_system_id: uuid.UUID
    target_layer: str
    db_name: str
    table_name: str
    catalog_uri: str
    location: str | None = None
    partition_cols: list[str] | None = None
    is_external: bool = True
    overrides: dict[str, FieldOverride] | None = None
    tech_template_id: uuid.UUID | None = None
    tech_overrides: list[TechFieldOverride] | None = None


class LakeSyncWarning(BaseModel):
    """One non-fatal observation surfaced from a lake-sync run."""

    field_name: str
    code: str
    detail: str


class LakeSyncResponse(BaseModel):
    """Response payload for a successful lake-sync."""

    target_dataset_id: uuid.UUID
    target_dataset_schema_id: uuid.UUID
    dataset_link_id: uuid.UUID
    mapped_field_count: int
    tech_field_count: int
    warnings: list[LakeSyncWarning] = Field(default_factory=list)
