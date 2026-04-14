from aide_schemas.system import SystemCreate, SystemRead, SystemUpdate
from aide_sdk.resources.base import BaseResource


class SystemsResource(BaseResource[SystemCreate, SystemRead, SystemUpdate]):
    _path = "/api/v1/systems"
    _read_schema = SystemRead
