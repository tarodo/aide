from aide_schemas.field import FieldCreate, FieldRead, FieldUpdate
from aide_sdk.resources.base import BaseResource


class FieldsResource(BaseResource[FieldCreate, FieldRead, FieldUpdate]):
    _path = "/api/v1/fields"
    _read_schema = FieldRead
