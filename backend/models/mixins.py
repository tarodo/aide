import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Mixin for created_at and updated_at fields."""

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserTrackingMixin:
    """Mixin for created_by and updated_by fields."""

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
    updated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
