import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class FieldLink(Base, MetaDataMixin):
    __tablename__ = "field_links"

    dataset_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dataset_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    dataset_link = relationship("DatasetLink", back_populates="field_links")

    __table_args__ = (
        UniqueConstraint(
            "dataset_link_id",
            "source_field_id",
            "target_field_id",
            name="uq_field_link_triple",
        ),
        UniqueConstraint(
            "dataset_link_id",
            "target_field_id",
            name="uq_field_link_target_in_link",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"FieldLink(id={self.id}, source={self.source_field_id}, "
            f"target={self.target_field_id})"
        )
