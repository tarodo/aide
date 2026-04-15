from uuid import UUID

from aide_schemas.type_instance import (
    TypeInstanceCreate,
    TypeInstanceRead,
    TypeInstanceTree,
    TypeInstanceUpdate,
)
from aide_sdk.resources.base import BaseResource


class TypeInstancesResource(
    BaseResource[TypeInstanceCreate, TypeInstanceRead, TypeInstanceUpdate]
):
    _path = "/api/v1/type-instances"
    _read_schema = TypeInstanceRead

    async def get_tree(self, obj_id: UUID) -> TypeInstanceTree:
        data = await self._http.get(f"{self._path}/{obj_id}/tree")
        return TypeInstanceTree.model_validate(data)
