import enum
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class CastSafety(str, enum.Enum):
    IMPLICIT = "implicit"
    SAFE = "safe"
    UNSAFE = "unsafe"


class CastRuleBase(BaseModel):
    """Base cast rule schema."""

    source_data_type_id: uuid.UUID
    target_data_type_id: uuid.UUID
    param_mapping: dict[str, Any]
    safety: CastSafety


class CastRuleCreate(CastRuleBase, NoteMixin):
    """Schema for cast rule creation."""

    pass


class CastRuleUpdate(VersionedUpdateMixin, NoteMixin):
    """Schema for cast rule update."""

    source_data_type_id: uuid.UUID | None = None
    target_data_type_id: uuid.UUID | None = None
    param_mapping: dict[str, Any] | None = None
    safety: CastSafety | None = None


class CastRuleRead(CastRuleBase, MetaDataMixin):
    """Schema for reading cast rule data."""

    model_config = ConfigDict(from_attributes=True)
