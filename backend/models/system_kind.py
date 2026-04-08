from sqlalchemy import Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import SoftDeleteMetaDataMixin


class SystemKind(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "system_kinds"

    code: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    flavors = relationship("SystemFlavor", back_populates="kind")

    __table_args__ = (
        Index(
            "uq_system_kinds_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"SystemKind(id={self.id}, code={self.code}, name={self.name})"
