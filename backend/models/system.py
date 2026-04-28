import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import SoftDeleteMetaDataMixin


class System(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "systems"

    code: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(255)), nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    flavor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("system_flavors.id"), nullable=False
    )
    credential_ref_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credential_refs.id"), nullable=True
    )

    flavor = relationship("SystemFlavor", back_populates="systems")
    credential_ref = relationship("CredentialRef", back_populates="systems")

    __table_args__ = (
        Index(
            "uq_systems_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"System(id={self.id}, code={self.code}, name={self.name})"
