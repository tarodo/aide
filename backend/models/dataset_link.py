import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import SoftDeleteMetaDataMixin


class DatasetLink(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "dataset_links"

    source_dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id"),
        nullable=False,
        index=True,
    )
    target_dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id"),
        nullable=False,
        index=True,
    )
    source_schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dataset_schemas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dataset_schemas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    engine_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("engines.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    source_dataset = relationship("Dataset", foreign_keys=[source_dataset_id])
    target_dataset = relationship("Dataset", foreign_keys=[target_dataset_id])
    source_schema = relationship("DatasetSchema", foreign_keys=[source_schema_id])
    target_schema = relationship("DatasetSchema", foreign_keys=[target_schema_id])
    field_links = relationship(
        "FieldLink",
        back_populates="dataset_link",
        cascade="all, delete-orphan",
    )
    engine = relationship("Engine")

    __table_args__ = (
        Index(
            "uq_dataset_link_pair_active",
            "source_dataset_id",
            "target_dataset_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "source_dataset_id <> target_dataset_id",
            name="ck_dataset_link_no_self",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"DatasetLink(id={self.id}, "
            f"source={self.source_dataset_id}, target={self.target_dataset_id}, "
            f"src_schema={self.source_schema_id}, tgt_schema={self.target_schema_id})"
        )
