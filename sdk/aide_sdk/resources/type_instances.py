from aide_schemas.type_instance import (
    TypeInstanceCreate,
    TypeInstanceRead,
    TypeInstanceUpdate,
)
from aide_sdk.resources.base import BaseResource


class TypeInstancesResource(
    BaseResource[TypeInstanceCreate, TypeInstanceRead, TypeInstanceUpdate]
):
    _path = "/api/v1/type-instances"
    _read_schema = TypeInstanceRead
