import enum
import uuid
from typing import Any, Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class DatasetLayer(str, enum.Enum):
    SOURCE = "source"
    CDC = "cdc"
    KAFKA = "kafka"
    RAW = "raw"
    CORE = "core"


LAYER_ORDER: dict[DatasetLayer, int] = {
    DatasetLayer.SOURCE: 0,
    DatasetLayer.CDC: 1,
    DatasetLayer.KAFKA: 2,
    DatasetLayer.RAW: 3,
    DatasetLayer.CORE: 4,
}


class DatasetPattern(str, enum.Enum):
    SCD1 = "scd1"
    SCD2 = "scd2"
    SNAPSHOT = "snapshot"
    APPEND_ONLY = "append_only"
    CDC_PAYLOAD = "cdc_payload"


# --- Base Schemas ---
class DatasetBase(BaseModel):
    system_id: uuid.UUID
    object_name: str
    layer: DatasetLayer | None = None
    is_active: bool = True
    extra: dict[str, Any] | None = None


class DatasetReadBase(DatasetBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)


class DatasetCreateBase(DatasetBase, NoteMixin):
    pass


# --- RDBMS ---
class DatasetRdbmsDetails(BaseModel):
    catalog_name: str | None = None
    schema_name: str
    table_name: str
    is_view: bool | None = False
    distribution: list[str] | None = None
    pk_columns: list[str] | None = None
    uq_constraints: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


class DatasetRdbmsCreate(DatasetCreateBase, DatasetRdbmsDetails):
    kind: Literal["rdbms"]


class DatasetRdbmsRead(DatasetReadBase, DatasetRdbmsDetails):
    kind: Literal["rdbms"]


# --- Kafka ---
class DatasetKafkaDetails(BaseModel):
    topic: str
    format: str
    partitions: int
    retention_ms: int
    key_columns: list[str]
    extra: dict[str, Any] | None = None


class DatasetKafkaCreate(DatasetCreateBase, DatasetKafkaDetails):
    kind: Literal["kafka"]


class DatasetKafkaRead(DatasetReadBase, DatasetKafkaDetails):
    kind: Literal["kafka"]


# --- Storage ---
class DatasetStorageDetails(BaseModel):
    path: str
    file_format: str
    compression: str | None = None
    partition_by: list[str] | None = None
    extra: dict[str, Any] | None = None


class DatasetStorageCreate(DatasetCreateBase, DatasetStorageDetails):
    kind: Literal["storage"]


class DatasetStorageRead(DatasetReadBase, DatasetStorageDetails):
    kind: Literal["storage"]


# --- SFTP ---
class DatasetSftpDetails(BaseModel):
    path: str
    file_format: str
    compression: str | None = None
    archive: str | None = None
    extra: dict[str, Any] | None = None


class DatasetSftpCreate(DatasetCreateBase, DatasetSftpDetails):
    kind: Literal["sftp"]


class DatasetSftpRead(DatasetReadBase, DatasetSftpDetails):
    kind: Literal["sftp"]


# --- Hive ---
class DatasetHiveDetails(BaseModel):
    catalog_uri: str
    db_name: str
    table_name: str
    is_external: bool = False
    file_format: str
    location: str | None = None
    partition_cols: list[str] | None = None
    serde: str | None = None
    tblproperties: dict[str, Any] | None = None
    bkey_columns: list[str] | None = None
    extra: dict[str, Any] | None = None


class DatasetHiveCreate(DatasetCreateBase, DatasetHiveDetails):
    kind: Literal["hive"]


class DatasetHiveRead(DatasetReadBase, DatasetHiveDetails):
    kind: Literal["hive"]


# --- Discriminated Unions ---
AnyDatasetCreate = Annotated[
    Union[
        DatasetRdbmsCreate,
        DatasetKafkaCreate,
        DatasetStorageCreate,
        DatasetSftpCreate,
        DatasetHiveCreate,
    ],
    Field(discriminator="kind"),
]

AnyDatasetRead = Annotated[
    Union[
        DatasetRdbmsRead,
        DatasetKafkaRead,
        DatasetStorageRead,
        DatasetSftpRead,
        DatasetHiveRead,
    ],
    Field(discriminator="kind"),
]

# Mapping for validation
READ_SCHEMA_MAP = {
    "rdbms": DatasetRdbmsRead,
    "kafka": DatasetKafkaRead,
    "storage": DatasetStorageRead,
    "sftp": DatasetSftpRead,
    "hive": DatasetHiveRead,
}


def validate_dataset_read(obj: Any) -> AnyDatasetRead:
    """Validate a dataset model into the appropriate read schema based on kind."""
    kind = getattr(obj, "kind", None)
    if not kind or kind not in READ_SCHEMA_MAP:
        raise ValueError(f"Unknown dataset kind: {kind}")
    schema_class = READ_SCHEMA_MAP[kind]
    # schema_class is one of the Read classes which all have model_validate
    return schema_class.model_validate(obj)  # type: ignore[attr-defined, return-value]


# --- Update Schemas ---


class DatasetUpdateBase(VersionedUpdateMixin, NoteMixin):
    """Base schema for dataset updates, containing common optional fields."""

    object_name: str | None = None
    layer: DatasetLayer | None = None
    is_active: bool | None = None
    extra: dict[str, Any] | None = None


class DatasetRdbmsUpdate(DatasetUpdateBase):
    kind: Literal["rdbms"]
    catalog_name: str | None = None
    schema_name: str | None = None
    table_name: str | None = None
    is_view: bool | None = None
    distribution: list[str] | None = None
    pk_columns: list[str] | None = None
    uq_constraints: dict[str, Any] | None = None


class DatasetKafkaUpdate(DatasetUpdateBase):
    kind: Literal["kafka"]
    topic: str | None = None
    format: str | None = None
    partitions: int | None = None
    retention_ms: int | None = None
    key_columns: list[str] | None = None


class DatasetStorageUpdate(DatasetUpdateBase):
    kind: Literal["storage"]
    path: str | None = None
    file_format: str | None = None
    compression: str | None = None
    partition_by: list[str] | None = None


class DatasetSftpUpdate(DatasetUpdateBase):
    kind: Literal["sftp"]
    path: str | None = None
    file_format: str | None = None
    compression: str | None = None
    archive: str | None = None


class DatasetHiveUpdate(DatasetUpdateBase):
    kind: Literal["hive"]
    catalog_uri: str | None = None
    db_name: str | None = None
    table_name: str | None = None
    is_external: bool | None = None
    file_format: str | None = None
    location: str | None = None
    partition_cols: list[str] | None = None
    serde: str | None = None
    tblproperties: dict[str, Any] | None = None
    bkey_columns: list[str] | None = None


AnyDatasetUpdate = Annotated[
    Union[
        DatasetRdbmsUpdate,
        DatasetKafkaUpdate,
        DatasetStorageUpdate,
        DatasetSftpUpdate,
        DatasetHiveUpdate,
    ],
    Field(discriminator="kind"),
]
