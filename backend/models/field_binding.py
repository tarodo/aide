import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class FieldBinding(Base, MetaDataMixin):
    __tablename__ = "field_bindings"

    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id"), nullable=False
    )
    dataset_schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_schemas.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_nullable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    data_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_types.id"), nullable=False, index=True
    )
    type_params: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    field = relationship("Field")
    dataset_schema = relationship("DatasetSchema")
    data_type = relationship("DataType")

    __table_args__ = (
        UniqueConstraint(
            "dataset_schema_id",
            "field_id",
            name="idx_field_binding_dataset_schema_id_field_id",
        ),
        UniqueConstraint(
            "dataset_schema_id",
            "position",
            name="idx_field_binding_dataset_schema_id_position",
        ),
    )

    def __repr__(self) -> str:
        return f"FieldBinding(id={self.id}, field_id={self.field_id}, dataset_schema_id={self.dataset_schema_id})"
