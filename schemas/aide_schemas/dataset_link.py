import uuid

from pydantic import BaseModel, ConfigDict, model_validator

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class DatasetLinkBase(BaseModel):
    source_dataset_id: uuid.UUID
    target_dataset_id: uuid.UUID
    source_schema_id: uuid.UUID
    target_schema_id: uuid.UUID


class DatasetLinkCreate(DatasetLinkBase, NoteMixin):
    pass


class DatasetLinkUpdate(VersionedUpdateMixin, NoteMixin):
    """DatasetLink update payload. Dataset IDs are immutable and absent here;
    `extra='forbid'` rejects them with 422 if clients send them anyway.
    Schema pin fields stay non-null (per existing contract). `engine_id` is
    explicitly nullable: clients can set or clear the engine pin.
    """

    model_config = ConfigDict(extra="forbid")

    source_schema_id: uuid.UUID | None = None
    target_schema_id: uuid.UUID | None = None
    engine_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def reject_explicit_null_pins(self) -> "DatasetLinkUpdate":
        for field_name in ("source_schema_id", "target_schema_id"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(
                    f"{field_name} cannot be explicitly null; "
                    "omit the key to leave the pin unchanged"
                )
        return self


class DatasetLinkRead(DatasetLinkBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
    engine_id: uuid.UUID | None = None
