import uuid

from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class FieldLinkBase(BaseModel):
    dataset_link_id: uuid.UUID
    source_field_id: uuid.UUID
    target_field_id: uuid.UUID


class FieldLinkCreate(FieldLinkBase, NoteMixin):
    pass


class FieldLinkUpdate(VersionedUpdateMixin, NoteMixin):
    pass


class FieldLinkRead(FieldLinkBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
