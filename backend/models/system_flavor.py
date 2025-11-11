import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class SystemFlavor(Base, MetaDataMixin):
    __tablename__ = "system_flavors"

    code: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    vendor: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[str | None] = mapped_column(String, nullable=True)

    kind_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("system_kinds.id"), nullable=False
    )
    kind = relationship("SystemKind", back_populates="flavors")

    def __repr__(self) -> str:
        return f"SystemFlavor(id={self.id}, code={self.code}, name={self.name})"
