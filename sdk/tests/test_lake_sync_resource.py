from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from aide_schemas.lake_sync import LakeSyncRequest, LakeSyncResponse
from aide_sdk.resources.lake_sync import LakeSyncResource


@pytest.mark.asyncio
async def test_lake_sync_create_posts_correct_path() -> None:
    http = AsyncMock()
    http.post.return_value = {
        "target_dataset_id": str(uuid.uuid4()),
        "target_dataset_schema_id": str(uuid.uuid4()),
        "dataset_link_id": str(uuid.uuid4()),
        "mapped_field_count": 1,
        "tech_field_count": 0,
        "warnings": [],
    }

    resource = LakeSyncResource(http=http)
    src_id = uuid.uuid4()
    req = LakeSyncRequest(
        target_system_id=uuid.uuid4(),
        target_layer="core",
        db_name="lake",
        table_name="users",
        catalog_uri="thrift://hms:9083",
    )
    resp = await resource.create(src_id, req)

    assert isinstance(resp, LakeSyncResponse)
    http.post.assert_awaited_once()
    args, kwargs = http.post.call_args
    assert args[0] == f"/api/v1/datasets/{src_id}/lake-sync"
    assert "json" in kwargs
    assert kwargs["json"]["db_name"] == "lake"
