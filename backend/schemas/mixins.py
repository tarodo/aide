import datetime
import uuid

from pydantic import BaseModel


class TimestampMixin(BaseModel):
    created_at: datetime.datetime
    updated_at: datetime.datetime


class UserTrackingMixin(BaseModel):
    created_by: uuid.UUID | None = None
    updated_by: uuid.UUID | None = None
