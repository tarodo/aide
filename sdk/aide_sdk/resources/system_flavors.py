from aide_schemas.system_flavor import (
    SystemFlavorCreate,
    SystemFlavorRead,
    SystemFlavorUpdate,
)
from aide_sdk.resources.base import BaseResource


class SystemFlavorsResource(
    BaseResource[SystemFlavorCreate, SystemFlavorRead, SystemFlavorUpdate]
):
    _path = "/api/v1/system-flavors"
    _read_schema = SystemFlavorRead
