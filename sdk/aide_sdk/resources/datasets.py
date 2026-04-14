from aide_schemas.dataset import AnyDatasetCreate, AnyDatasetRead, AnyDatasetUpdate
from aide_sdk.resources.base import BaseResource


class DatasetsResource(
    BaseResource[AnyDatasetCreate, AnyDatasetRead, AnyDatasetUpdate]
):
    _path = "/api/v1/datasets"
    _read_schema = AnyDatasetRead
