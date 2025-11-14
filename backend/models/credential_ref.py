from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class CredentialRef(Base, MetaDataMixin):
    __tablename__ = "credential_refs"

    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    systems = relationship("System", back_populates="credential_ref")

    __table_args__ = (
        UniqueConstraint("provider", "path", name="idx_credential_ref_provider_path"),
    )

    def __repr__(self) -> str:
        return (
            f"CredentialRef(id={self.id}, provider={self.provider}, path={self.path})"
        )
