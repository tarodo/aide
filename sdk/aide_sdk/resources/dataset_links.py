from __future__ import annotations

from typing import Any, List
from uuid import UUID

from aide_schemas.dataset_link import (
    DatasetLinkCreate,
    DatasetLinkRead,
    DatasetLinkUpdate,
)
from aide_schemas.engine import RenderResult
from aide_schemas.lineage_compat import (
    DatasetLinkCompatReport,
    DatasetLinkCompatSummary,
)
from aide_schemas.pagination import Page
from aide_sdk.resources.base import BaseResource


class DatasetLinksResource(
    BaseResource[DatasetLinkCreate, DatasetLinkRead, DatasetLinkUpdate]
):
    _path = "/api/v1/dataset-links"
    _read_schema = DatasetLinkRead

    async def compat(self, obj_id: UUID) -> DatasetLinkCompatReport:
        data = await self._http.get(f"{self._path}/{obj_id}/compat")
        return DatasetLinkCompatReport.model_validate(data)

    async def list_compat(
        self,
        *,
        status: List[str] | None = None,
        has_drift: bool | None = None,
        dataset_id: UUID | None = None,
        system_id: UUID | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[DatasetLinkCompatSummary]:
        params: dict[str, Any] = {"page": page, "size": size}
        if status is not None:
            params["status"] = ",".join(status)
        if has_drift is not None:
            params["has_drift"] = has_drift
        if dataset_id is not None:
            params["dataset_id"] = str(dataset_id)
        if system_id is not None:
            params["system_id"] = str(system_id)
        data = await self._http.get(f"{self._path}/compat", params=params)
        return Page[DatasetLinkCompatSummary].model_validate(data)

    async def render_sql(self, obj_id: UUID) -> RenderResult:
        data = await self._http.post(f"{self._path}/{obj_id}/render-sql")
        return RenderResult.model_validate(data)
