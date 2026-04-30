import uuid
from unittest.mock import AsyncMock

import pytest

from aide_schemas.engine import EngineSparkRead, RenderResult
from aide_sdk.resources.engines import EnginesResource


@pytest.mark.asyncio
async def test_engines_get_returns_polymorphic_read():
    http = AsyncMock()
    http.get = AsyncMock(
        return_value={
            "id": str(uuid.uuid4()),
            "kind": "spark",
            "role": "compute",
            "code": "s",
            "name": "n",
            "version": "3.x",
            "runtime_opts": None,
            "created_at": "2026-04-30T00:00:00",
            "updated_at": "2026-04-30T00:00:00",
            "row_version": 1,
        }
    )
    res = EnginesResource(http)
    out = await res.get(uuid.uuid4())
    assert isinstance(out, EngineSparkRead)
    assert out.code == "s"


@pytest.mark.asyncio
async def test_dataset_links_render_sql():
    http = AsyncMock()
    http.post = AsyncMock(
        return_value={
            "engine_id": str(uuid.uuid4()),
            "engine_kind": "spark",
            "sql": "INSERT INTO x SELECT * FROM y;",
            "warnings": [],
        }
    )
    from aide_sdk.resources.dataset_links import DatasetLinksResource

    res = DatasetLinksResource(http)
    out = await res.render_sql(uuid.uuid4())
    assert isinstance(out, RenderResult)
    assert "INSERT" in out.sql
