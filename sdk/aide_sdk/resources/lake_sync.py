from __future__ import annotations

import uuid

from aide_schemas.lake_sync import LakeSyncRequest, LakeSyncResponse


class LakeSyncResource:
    def __init__(self, http) -> None:
        self._http = http

    async def create(
        self, source_dataset_id: uuid.UUID, request: LakeSyncRequest
    ) -> LakeSyncResponse:
        data = await self._http.post(
            f"/api/v1/datasets/{source_dataset_id}/lake-sync",
            json=request.model_dump(mode="json", exclude_none=True),
        )
        return LakeSyncResponse.model_validate(data)
