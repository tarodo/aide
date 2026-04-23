import uuid

from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class DatasetLinkBase(BaseModel):
    source_dataset_id: uuid.UUID
    target_dataset_id: uuid.UUID
    source_schema_id: uuid.UUID
    target_schema_id: uuid.UUID


class DatasetLinkCreate(DatasetLinkBase, NoteMixin):
    pass


class DatasetLinkUpdate(VersionedUpdateMixin, NoteMixin):
    """Dataset IDs are immutable — omitted here. Pydantic rejects them as extras."""

    source_schema_id: uuid.UUID | None = None
    target_schema_id: uuid.UUID | None = None


class DatasetLinkRead(DatasetLinkBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
