from __future__ import annotations

import uuid
from typing import Any

from pydantic import ConfigDict

from backend.schemas.mixins import MetaDataMixin, NoteMixin


class TypeInstanceCreate(NoteMixin):
    """Schema for type instance creation."""

    data_type_id: uuid.UUID
    type_params: dict[str, Any] | None = None
    parent_id: uuid.UUID | None = None
    slot: str | None = None


class TypeInstanceUpdate(NoteMixin):
    """Schema for type instance update (parent_id and slot are immutable)."""

    data_type_id: uuid.UUID | None = None
    type_params: dict[str, Any] | None = None


class TypeInstanceRead(MetaDataMixin):
    """Schema for reading a flat type instance."""

    model_config = ConfigDict(from_attributes=True)

    data_type_id: uuid.UUID
    type_params: dict[str, Any] | None
    parent_id: uuid.UUID | None
    slot: str | None


class TypeInstanceTree(MetaDataMixin):
    """Recursive schema for reading a type instance tree."""

    model_config = ConfigDict(from_attributes=True)

    data_type_id: uuid.UUID
    type_params: dict[str, Any] | None
    slot: str | None
    children: list[TypeInstanceTree]
