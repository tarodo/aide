import uuid

from pydantic import BaseModel, ConfigDict

from aide_schemas.dataset import DatasetLayer
from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class TechFieldTemplateFieldBase(BaseModel):
    name: str
    type_code: str
    order: int = 0


class TechFieldTemplateFieldCreate(TechFieldTemplateFieldBase, NoteMixin):
    template_id: uuid.UUID


class TechFieldTemplateFieldUpdate(VersionedUpdateMixin, NoteMixin):
    name: str | None = None
    type_code: str | None = None
    order: int | None = None


class TechFieldTemplateFieldRead(TechFieldTemplateFieldBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
    template_id: uuid.UUID


class TechFieldTemplateBase(BaseModel):
    code: str
    name: str
    layer: DatasetLayer


class TechFieldTemplateCreate(TechFieldTemplateBase, NoteMixin):
    pass


class TechFieldTemplateUpdate(VersionedUpdateMixin, NoteMixin):
    code: str | None = None
    name: str | None = None
    layer: DatasetLayer | None = None


class TechFieldTemplateRead(TechFieldTemplateBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)


class TechFieldTemplateWithFieldsRead(TechFieldTemplateRead):
    fields: list[TechFieldTemplateFieldRead] = []


class TechFieldOverride(BaseModel):
    """Per-field override at apply-template time."""

    name: str
    type_code: str | None = None


class ApplyTechTemplateRequest(BaseModel):
    template_id: uuid.UUID
    overrides: list[TechFieldOverride] | None = None
