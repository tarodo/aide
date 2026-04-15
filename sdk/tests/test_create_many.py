import uuid
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from aide_sdk.resources.base import BaseResource


class _Create(BaseModel):
    name: str


class _Read(BaseModel):
    id: uuid.UUID
    name: str


class _Resource(BaseResource[_Create, _Read, _Create]):
    _path = "/things"
    _read_schema = _Read


def _read_row(name: str) -> dict:
    return {"id": str(uuid.uuid4()), "name": name}


@pytest.mark.asyncio
async def test_create_many_empty_skips_http():
    http = AsyncMock()
    resource = _Resource(http)
    result = await resource.create_many([])
    assert result == []
    http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_many_single_chunk():
    http = AsyncMock()
    http.post = AsyncMock(
        return_value={
            "items": [_read_row("a"), _read_row("b")],
            "count": 2,
        }
    )
    resource = _Resource(http)
    result = await resource.create_many([_Create(name="a"), _Create(name="b")])
    assert len(result) == 2
    assert [r.name for r in result] == ["a", "b"]
    http.post.assert_awaited_once()
    args, kwargs = http.post.call_args
    assert args[0] == "/things/batch"
    assert kwargs["json"] == {"items": [{"name": "a"}, {"name": "b"}]}


@pytest.mark.asyncio
async def test_create_many_chunks_on_size():
    http = AsyncMock()

    calls: list[int] = []

    async def fake_post(path, *, json):
        size = len(json["items"])
        calls.append(size)
        return {
            "items": [_read_row(f"x_{i}") for i in range(size)],
            "count": size,
        }

    http.post = AsyncMock(side_effect=fake_post)
    resource = _Resource(http)

    items = [_Create(name=f"n_{i}") for i in range(1200)]
    result = await resource.create_many(items, chunk_size=500)
    assert len(result) == 1200
    assert calls == [500, 500, 200]


@pytest.mark.asyncio
async def test_create_many_mid_chunk_error_propagates():
    http = AsyncMock()

    async def fake_post(path, *, json):
        if json["items"][0]["name"] == "boom":
            raise RuntimeError("server error")
        size = len(json["items"])
        return {
            "items": [_read_row(i["name"]) for i in json["items"]],
            "count": size,
        }

    http.post = AsyncMock(side_effect=fake_post)
    resource = _Resource(http)

    items = [
        *[_Create(name=f"ok_{i}") for i in range(3)],
        _Create(name="boom"),
    ]
    with pytest.raises(RuntimeError):
        await resource.create_many(items, chunk_size=3)
