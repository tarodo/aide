from sqlalchemy import Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import SoftDeleteMetaDataMixin


class CredentialRef(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "credential_refs"

    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    systems = relationship("System", back_populates="credential_ref")

    __table_args__ = (
        Index(
            "uq_credential_refs_provider_path_active",
            "provider",
            "path",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"CredentialRef(id={self.id}, provider={self.provider}, path={self.path})"
        )
