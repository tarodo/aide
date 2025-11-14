import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class DataType(Base, MetaDataMixin):
    __tablename__ = "data_types"

    system_flavor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("system_flavors.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(255), nullable=False)
    params_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    render_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    system_flavor = relationship("SystemFlavor", back_populates="data_types")

    __table_args__ = (
        UniqueConstraint(
            "system_flavor_id", "code", name="idx_data_type_system_flavor_id_code"
        ),
    )

    def __repr__(self) -> str:
        return f"DataType(id={self.id}, code={self.code}, system_flavor_id={self.system_flavor_id})"
