from aide_schemas.engine import AnyEngineCreate, AnyEngineRead, AnyEngineUpdate
from aide_sdk.resources.base import BaseResource


class EnginesResource(BaseResource[AnyEngineCreate, AnyEngineRead, AnyEngineUpdate]):
    _path = "/api/v1/engines"
    _read_schema = AnyEngineRead  # type: ignore[assignment]
