import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class Field(Base, MetaDataMixin):
    __tablename__ = "fields"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    pii_tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    dataset = relationship("Dataset")
    parent = relationship("Field", remote_side="Field.id", back_populates="children")
    children = relationship(
        "Field",
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "idx_field_root_name",
            "dataset_id",
            "name",
            unique=True,
            postgresql_where=(parent_id.is_(None)),
        ),
        Index(
            "idx_field_nested_name",
            "dataset_id",
            "parent_id",
            "name",
            unique=True,
            postgresql_where=(parent_id.isnot(None)),
        ),
    )

    def __repr__(self) -> str:
        return f"Field(id={self.id}, name={self.name}, dataset_id={self.dataset_id}, parent_id={self.parent_id})"
