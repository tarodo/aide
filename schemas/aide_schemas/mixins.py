import datetime
import uuid

from pydantic import BaseModel


class UUIDMixin(BaseModel):
    id: uuid.UUID


class TimestampMixin(BaseModel):
    created_at: datetime.datetime
    updated_at: datetime.datetime


class UserTrackingMixin(BaseModel):
    created_by: uuid.UUID | None = None
    updated_by: uuid.UUID | None = None


class NoteMixin(BaseModel):
    note: str | None = None


class VersionMixin(BaseModel):
    row_version: int


class VersionedUpdateMixin(BaseModel):
    row_version: int


class MetaDataMixin(
    UUIDMixin, TimestampMixin, UserTrackingMixin, NoteMixin, VersionMixin
):
    pass
