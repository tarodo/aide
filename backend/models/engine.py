import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.models.mixins import SoftDeleteMetaDataMixin


class Engine(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "engines"

    code: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "engine",
        "polymorphic_on": "kind",
    }

    __table_args__ = (
        Index(
            "uq_engines_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("role IN ('cdc', 'compute')", name="ck_engines_role"),
    )

    def __repr__(self) -> str:
        return f"Engine(id={self.id}, code={self.code}, kind={self.kind})"


class EngineDebezium(Engine):
    __tablename__ = "engine_debezium"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engines.id"), primary_key=True
    )
    envelope_template: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )
    topic_routing: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    __mapper_args__ = {"polymorphic_identity": "debezium"}


class EngineOgg(Engine):
    __tablename__ = "engine_ogg"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engines.id"), primary_key=True
    )
    envelope_template: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )
    topic_routing: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    __mapper_args__ = {"polymorphic_identity": "ogg"}


class EngineSpark(Engine):
    __tablename__ = "engine_spark"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engines.id"), primary_key=True
    )
    runtime_opts: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    __mapper_args__ = {"polymorphic_identity": "spark"}


class EngineImpala(Engine):
    __tablename__ = "engine_impala"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engines.id"), primary_key=True
    )
    runtime_opts: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    __mapper_args__ = {"polymorphic_identity": "impala"}
