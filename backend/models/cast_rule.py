import enum
import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, TypeDecorator, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class CastSafety(enum.Enum):
    IMPLICIT = "implicit"
    SAFE = "safe"
    UNSAFE = "unsafe"


class CastSafetyType(TypeDecorator):
    """Type decorator to convert between enum values (API) and enum names (DB)."""

    impl = Enum(
        "IMPLICIT",
        "SAFE",
        "UNSAFE",
        name="castsafety",
        native_enum=True,
        create_type=False,
    )
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Convert enum value to enum name for database storage."""
        if value is None:
            return None
        if isinstance(value, CastSafety):
            return value.name  # Use enum name (IMPLICIT, SAFE, UNSAFE) for DB
        if isinstance(value, str):
            # If it's a string from API (lowercase), convert to enum then to name
            try:
                return CastSafety(value).name
            except ValueError:
                # If not found by value, assume it's already a name (uppercase)
                return value.upper()
        return value

    def process_result_value(self, value, dialect):
        """Convert enum name from database to enum value."""
        if value is None:
            return None
        if isinstance(value, str):
            # Convert DB enum name (uppercase) to Python enum
            try:
                return CastSafety[value]
            except KeyError:
                # If not found by name, try by value (lowercase)
                return CastSafety(value)
        # If it's already a CastSafety enum, return as-is
        return value


class CastRule(Base, MetaDataMixin):
    __tablename__ = "cast_rules"

    source_data_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_data_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    param_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    safety: Mapped[CastSafety] = mapped_column(CastSafetyType(), nullable=False)

    source_data_type = relationship("DataType", foreign_keys=[source_data_type_id])
    target_data_type = relationship("DataType", foreign_keys=[target_data_type_id])

    __table_args__ = (
        UniqueConstraint(
            "source_data_type_id",
            "target_data_type_id",
            name="idx_cast_rule_source_target_data_type_id",
        ),
    )

    def __repr__(self) -> str:
        return f"CastRule(id={self.id}, source={self.source_data_type_id}, target={self.target_data_type_id})"
