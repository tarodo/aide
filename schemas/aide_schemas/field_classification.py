from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin


class FieldClassificationBase(BaseModel):
    """Base field classification schema."""

    field_id: uuid.UUID
    pii_tags: list[str]
    reason: str | None = None


class FieldClassificationCreate(FieldClassificationBase, NoteMixin):
    """Schema for creating a classification entry. Append-only: every POST is a new row."""

    pass


class FieldClassificationRead(FieldClassificationBase, MetaDataMixin):
    """Schema for reading a classification row."""

    model_config = ConfigDict(from_attributes=True)
