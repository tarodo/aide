from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class SystemKind(Base, MetaDataMixin):
    __tablename__ = "system_kinds"

    code: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    flavors = relationship("SystemFlavor", back_populates="kind")

    def __repr__(self) -> str:
        return f"SystemKind(id={self.id}, code={self.code}, name={self.name})"
