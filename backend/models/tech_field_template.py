import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class TechFieldTemplate(Base, MetaDataMixin):
    __tablename__ = "tech_field_templates"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    layer: Mapped[str] = mapped_column(String(32), nullable=False)

    fields = relationship(
        "TechFieldTemplateField",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TechFieldTemplateField.order",
    )

    def __repr__(self) -> str:
        return f"TechFieldTemplate(id={self.id}, code={self.code}, layer={self.layer})"


class TechFieldTemplateField(Base, MetaDataMixin):
    __tablename__ = "tech_field_template_fields"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tech_field_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    template = relationship("TechFieldTemplate", back_populates="fields")

    __table_args__ = (
        UniqueConstraint("template_id", "name", name="uq_tft_field_name"),
    )

    def __repr__(self) -> str:
        return (
            f"TechFieldTemplateField(id={self.id}, template_id={self.template_id}, "
            f"name={self.name}, type_code={self.type_code})"
        )
