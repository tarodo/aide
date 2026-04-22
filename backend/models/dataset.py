import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import SoftDeleteMetaDataMixin


class Dataset(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "datasets"

    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("systems.id"), nullable=False, index=True
    )
    object_name: Mapped[str] = mapped_column(Text, nullable=False)
    layer: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    kind: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    pattern_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    system = relationship("System")

    __table_args__ = (
        Index(
            "uq_datasets_system_id_object_name_active",
            "system_id",
            "object_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    __mapper_args__ = {
        "polymorphic_identity": "dataset",
        "polymorphic_on": "kind",
    }

    def __repr__(self) -> str:
        return (
            f"Dataset(id={self.id}, object_name={self.object_name}, kind={self.kind})"
        )


class DatasetRdbms(Dataset):
    __tablename__ = "dataset_rdbms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), primary_key=True
    )
    catalog_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_name: Mapped[str] = mapped_column(Text, nullable=False)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_view: Mapped[bool | None] = mapped_column(Boolean, default=False)
    distribution: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(255)), nullable=True
    )
    pk_columns: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(255)), nullable=True
    )
    uq_constraints: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": "rdbms",
    }


class DatasetKafka(Dataset):
    __tablename__ = "dataset_kafka"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), primary_key=True
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(255), nullable=False)
    partitions: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    key_columns: Mapped[list[str]] = mapped_column(ARRAY(String(255)), nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "kafka",
    }


class DatasetStorage(Dataset):
    __tablename__ = "dataset_storage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), primary_key=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(String(255), nullable=False)
    compression: Mapped[str | None] = mapped_column(String(255), nullable=True)
    partition_by: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(255)), nullable=True
    )

    __mapper_args__ = {
        "polymorphic_identity": "storage",
    }


class DatasetSftp(Dataset):
    __tablename__ = "dataset_sftp"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), primary_key=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(String(255), nullable=False)
    compression: Mapped[str | None] = mapped_column(String(255), nullable=True)
    archive: Mapped[str | None] = mapped_column(Text, nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": "sftp",
    }


class DatasetHive(Dataset):
    __tablename__ = "dataset_hive"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), primary_key=True
    )
    catalog_uri: Mapped[str] = mapped_column(Text, nullable=False)
    db_name: Mapped[str] = mapped_column(Text, nullable=False)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_external: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    file_format: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    partition_cols: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(255)), nullable=True
    )
    serde: Mapped[str | None] = mapped_column(Text, nullable=True)
    tblproperties: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    bkey_columns: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(255)), nullable=True
    )

    __mapper_args__ = {
        "polymorphic_identity": "hive",
    }
