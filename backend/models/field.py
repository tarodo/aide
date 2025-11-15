import uuid
from typing import Any

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class Field(Base, MetaDataMixin):
    __tablename__ = "fields"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    pii_tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    dataset = relationship("Dataset")

    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="idx_field_dataset_id_name"),
    )

    def __repr__(self) -> str:
        return f"Field(id={self.id}, name={self.name}, dataset_id={self.dataset_id})"
