from aide_schemas.data_type import DataTypeCreate, DataTypeRead, DataTypeUpdate
from aide_sdk.resources.base import BaseResource


class DataTypesResource(BaseResource[DataTypeCreate, DataTypeRead, DataTypeUpdate]):
    _path = "/api/v1/data-types"
    _read_schema = DataTypeRead
