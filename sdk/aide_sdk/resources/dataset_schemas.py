from aide_schemas.dataset_schema import (
    DatasetSchemaCreate,
    DatasetSchemaRead,
    DatasetSchemaUpdate,
)
from aide_sdk.resources.base import BaseResource


class DatasetSchemasResource(
    BaseResource[DatasetSchemaCreate, DatasetSchemaRead, DatasetSchemaUpdate]
):
    _path = "/api/v1/dataset-schemas"
    _read_schema = DatasetSchemaRead
