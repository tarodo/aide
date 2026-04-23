from __future__ import annotations

import enum
import uuid

from pydantic import BaseModel, ConfigDict


class FieldCompatIssue(str, enum.Enum):
    """Issues surfaced for one FieldLink under a DatasetLink's pinned schemas."""

    SOURCE_UNBOUND = "source_unbound"
    TARGET_UNBOUND = "target_unbound"
    TYPE_INCOMPATIBLE = "type_incompatible"
    TYPE_UNSAFE_CAST = "type_unsafe_cast"
    TYPE_NEEDS_CAST = "type_needs_cast"
    NULLABILITY_WARN = "nullability_warn"


class CompatSeverity(str, enum.Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


class PinDriftSide(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pinned_version: int
    latest_version: int
    has_drift: bool


class PinDrift(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: PinDriftSide
    target: PinDriftSide


class FieldCompatFieldRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class FieldCompatRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field_link_id: uuid.UUID
    source_field: FieldCompatFieldRef
    target_field: FieldCompatFieldRef
    source_type: str | None
    target_type: str | None
    issues: list[FieldCompatIssue]
    severity: CompatSeverity
    cast_rule_id: uuid.UUID | None


class CompatSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ok: int
    warn: int
    error: int
    total: int


class DatasetRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    object_name: str


class DatasetLinkCompatReport(BaseModel):
    """Full compat report for a single DatasetLink."""

    model_config = ConfigDict(from_attributes=True)

    dataset_link_id: uuid.UUID
    pin_drift: PinDrift
    field_compat: list[FieldCompatRow]
    summary: CompatSummary
    status: CompatSeverity


class DatasetLinkCompatSummary(BaseModel):
    """Lightweight per-link summary for bulk monitoring listing."""

    model_config = ConfigDict(from_attributes=True)

    dataset_link_id: uuid.UUID
    source_dataset: DatasetRef
    target_dataset: DatasetRef
    status: CompatSeverity
    summary: CompatSummary
    pin_drift: dict[str, bool]  # {"source": bool, "target": bool}
