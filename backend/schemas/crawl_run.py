import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class CrawlStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CrawlRunBase(BaseModel):
    system_id: uuid.UUID
    status: CrawlStatus
    started_at: datetime
    config: dict[str, Any]


class CrawlRunCreate(CrawlRunBase, NoteMixin):
    pass


class CrawlRunUpdate(VersionedUpdateMixin, NoteMixin):
    status: CrawlStatus | None = None
    finished_at: datetime | None = None
    summary: dict[str, Any] | None = None
    error_message: str | None = None


class CrawlRunRead(CrawlRunBase, MetaDataMixin):
    finished_at: datetime | None = None
    summary: dict[str, Any] | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)
