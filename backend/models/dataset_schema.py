import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class DatasetSchema(Base, MetaDataMixin):
    __tablename__ = "dataset_schemas"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_num: Mapped[int] = mapped_column(Integer, nullable=False)
    schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    dataset = relationship("Dataset")

    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "version_num",
            name="idx_dataset_schema_dataset_id_version_num",
        ),
    )

    def __repr__(self) -> str:
        return f"DatasetSchema(id={self.id}, dataset_id={self.dataset_id}, version={self.version_num})"
