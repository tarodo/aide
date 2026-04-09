import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class TypeInstance(Base, MetaDataMixin):
    __tablename__ = "type_instances"

    data_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type_params: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("type_instances.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    slot: Mapped[str | None] = mapped_column(String(255), nullable=True)

    data_type = relationship("DataType")
    parent = relationship("TypeInstance", remote_side="TypeInstance.id", back_populates="children")
    children = relationship(
        "TypeInstance",
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("parent_id", "slot", name="uq_type_instance_parent_slot"),
    )

    def __repr__(self) -> str:
        return f"TypeInstance(id={self.id}, data_type_id={self.data_type_id}, parent_id={self.parent_id}, slot={self.slot})"
