import uuid

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import SoftDeleteMetaDataMixin


class SystemFlavor(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "system_flavors"

    code: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    vendor: Mapped[str | None] = mapped_column(Text, nullable=True)
    versions: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(255)), nullable=True
    )

    kind_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("system_kinds.id"), nullable=False
    )
    kind = relationship("SystemKind", back_populates="flavors")
    data_types = relationship("DataType", back_populates="system_flavor")
    systems = relationship("System", back_populates="flavor")

    __table_args__ = (
        Index(
            "uq_system_flavors_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"SystemFlavor(id={self.id}, code={self.code}, name={self.name})"
