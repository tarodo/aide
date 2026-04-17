import uuid

from sqlalchemy import ForeignKey, Index, Text, desc
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class FieldClassification(Base, MetaDataMixin):
    __tablename__ = "field_classifications"

    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=False,
    )
    pii_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    field = relationship("Field")

    __table_args__ = (
        Index(
            "ix_field_classifications_field_id_created_at",
            "field_id",
            desc("created_at"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"FieldClassification(id={self.id}, field_id={self.field_id}, "
            f"pii_tags={self.pii_tags})"
        )
