from aide_schemas.field_binding import (
    FieldBindingCreate,
    FieldBindingRead,
    FieldBindingUpdate,
)
from aide_sdk.resources.base import BaseResource


class FieldBindingsResource(
    BaseResource[FieldBindingCreate, FieldBindingRead, FieldBindingUpdate]
):
    _path = "/api/v1/field-bindings"
    _read_schema = FieldBindingRead
