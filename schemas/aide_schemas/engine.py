import enum
import uuid
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class EngineRole(str, enum.Enum):
    CDC = "cdc"
    COMPUTE = "compute"


class EngineKind(str, enum.Enum):
    DEBEZIUM = "debezium"
    OGG = "ogg"
    SPARK = "spark"
    IMPALA = "impala"


class _EngineBase(BaseModel):
    code: str
    name: str


class _CdcEnvelopeMixin(BaseModel):
    envelope_template: dict[str, Any]
    topic_routing: dict[str, Any] | None = None


class _CdcEnvelopeCreateMixin(_CdcEnvelopeMixin):
    @model_validator(mode="after")
    def _require_after_path(self) -> "_CdcEnvelopeCreateMixin":
        if "after_path" not in self.envelope_template:
            raise ValueError("envelope_template must include 'after_path'")
        return self


class _ComputeOptsMixin(BaseModel):
    runtime_opts: dict[str, Any] | None = None


# Debezium ---------------------------------------------------------------
class EngineDebeziumCreate(_EngineBase, _CdcEnvelopeCreateMixin, NoteMixin):
    kind: Literal["debezium"] = "debezium"
    role: Literal["cdc"] = "cdc"
    version: Literal["2.x", "1.x"]


class EngineDebeziumRead(_EngineBase, _CdcEnvelopeMixin, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
    kind: Literal["debezium"]
    role: Literal["cdc"]
    version: str


class EngineDebeziumUpdate(VersionedUpdateMixin, NoteMixin):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["debezium"]
    name: str | None = None
    version: Literal["2.x", "1.x"] | None = None
    envelope_template: dict[str, Any] | None = None
    topic_routing: dict[str, Any] | None = None


# OGG --------------------------------------------------------------------
class EngineOggCreate(_EngineBase, _CdcEnvelopeCreateMixin, NoteMixin):
    kind: Literal["ogg"] = "ogg"
    role: Literal["cdc"] = "cdc"
    version: Literal["21c", "19c"]


class EngineOggRead(_EngineBase, _CdcEnvelopeMixin, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
    kind: Literal["ogg"]
    role: Literal["cdc"]
    version: str


class EngineOggUpdate(VersionedUpdateMixin, NoteMixin):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["ogg"]
    name: str | None = None
    version: Literal["21c", "19c"] | None = None
    envelope_template: dict[str, Any] | None = None
    topic_routing: dict[str, Any] | None = None


# Spark ------------------------------------------------------------------
class EngineSparkCreate(_EngineBase, _ComputeOptsMixin, NoteMixin):
    kind: Literal["spark"] = "spark"
    role: Literal["compute"] = "compute"
    version: Literal["3.x", "4.x"]


class EngineSparkRead(_EngineBase, _ComputeOptsMixin, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
    kind: Literal["spark"]
    role: Literal["compute"]
    version: str


class EngineSparkUpdate(VersionedUpdateMixin, NoteMixin):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["spark"]
    name: str | None = None
    version: Literal["3.x", "4.x"] | None = None
    runtime_opts: dict[str, Any] | None = None


# Impala -----------------------------------------------------------------
class EngineImpalaCreate(_EngineBase, _ComputeOptsMixin, NoteMixin):
    kind: Literal["impala"] = "impala"
    role: Literal["compute"] = "compute"
    version: Literal["4.x"]


class EngineImpalaRead(_EngineBase, _ComputeOptsMixin, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
    kind: Literal["impala"]
    role: Literal["compute"]
    version: str


class EngineImpalaUpdate(VersionedUpdateMixin, NoteMixin):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["impala"]
    name: str | None = None
    version: Literal["4.x"] | None = None
    runtime_opts: dict[str, Any] | None = None


# Discriminated Unions ---------------------------------------------------
AnyEngineCreate = Annotated[
    Union[
        EngineDebeziumCreate,
        EngineOggCreate,
        EngineSparkCreate,
        EngineImpalaCreate,
    ],
    Field(discriminator="kind"),
]

AnyEngineRead = Annotated[
    Union[
        EngineDebeziumRead,
        EngineOggRead,
        EngineSparkRead,
        EngineImpalaRead,
    ],
    Field(discriminator="kind"),
]

AnyEngineUpdate = Annotated[
    Union[
        EngineDebeziumUpdate,
        EngineOggUpdate,
        EngineSparkUpdate,
        EngineImpalaUpdate,
    ],
    Field(discriminator="kind"),
]

READ_SCHEMA_MAP = {
    "debezium": EngineDebeziumRead,
    "ogg": EngineOggRead,
    "spark": EngineSparkRead,
    "impala": EngineImpalaRead,
}


def validate_engine_read(obj: Any) -> AnyEngineRead:
    kind = getattr(obj, "kind", None)
    if not kind or kind not in READ_SCHEMA_MAP:
        raise ValueError(f"Unknown engine kind: {kind}")
    schema_class = READ_SCHEMA_MAP[kind]
    return schema_class.model_validate(obj)  # type: ignore[attr-defined, return-value]


# Render result ----------------------------------------------------------
class RenderWarning(BaseModel):
    code: str
    field: str | None = None
    message: str | None = None
    extra: dict[str, Any] | None = None


class RenderResult(BaseModel):
    engine_id: uuid.UUID
    engine_kind: str
    sql: str
    warnings: list[RenderWarning] = Field(default_factory=list)
