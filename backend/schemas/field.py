from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class FieldBase(BaseModel):
    """Base field schema."""

    dataset_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    name: str
    path: str | None = None
    pii_tags: list[str] | None = None
    extra: dict[str, Any] | None = None


class FieldCreate(FieldBase, NoteMixin):
    """Schema for field creation."""

    pass


class FieldUpdate(VersionedUpdateMixin, NoteMixin):
    """Schema for field update."""

    dataset_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    name: str | None = None
    path: str | None = None
    pii_tags: list[str] | None = None
    extra: dict[str, Any] | None = None


class FieldRead(FieldBase, MetaDataMixin):
    """Schema for reading field data."""

    model_config = ConfigDict(from_attributes=True)


class FieldTree(MetaDataMixin):
    """Recursive schema for reading a field tree."""

    model_config = ConfigDict(from_attributes=True)

    dataset_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    path: str | None
    pii_tags: list[str] | None
    extra: dict[str, Any] | None
    children: list[FieldTree]
