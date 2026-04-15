import uuid

import pytest

from aide_crawler.errors import TypeNotInFlavorError
from aide_crawler.type_cache import TypeCache


class _Page:
    def __init__(self, items, pages):
        self.items = items
        self.pages = pages


class _Item:
    def __init__(self, id, code):
        self.id = id
        self.code = code


class _DataTypesStub:
    def __init__(self, items):
        self._items = items
        self.calls = []

    async def list(self, *, page=1, size=100, params=None):
        self.calls.append((page, size, params))
        start = (page - 1) * size
        chunk = self._items[start : start + size]
        pages = max(1, (len(self._items) + size - 1) // size)
        return _Page(chunk, pages)


class _ClientStub:
    def __init__(self, items):
        self.data_types = _DataTypesStub(items)


@pytest.mark.asyncio
async def test_load_paginates_and_resolves():
    flavor_id = uuid.uuid4()
    id_int = uuid.uuid4()
    id_num = uuid.uuid4()
    client = _ClientStub([_Item(id_int, "integer"), _Item(id_num, "numeric")])
    cache = await TypeCache.load(client, flavor_id=flavor_id, flavor_code="postgres14")
    assert cache.resolve("integer") == id_int
    assert cache.resolve("numeric") == id_num
    assert len(cache) == 2
    # Confirms flavor filter was passed
    assert client.data_types.calls[0][2] == {"system_flavor_id": str(flavor_id)}


@pytest.mark.asyncio
async def test_load_handles_multiple_pages():
    flavor_id = uuid.uuid4()
    items = [_Item(uuid.uuid4(), f"code_{i}") for i in range(250)]
    client = _ClientStub(items)
    cache = await TypeCache.load(client, flavor_id=flavor_id)
    assert len(cache) == 250
    # Default page size 100 => 3 pages fetched
    assert len(client.data_types.calls) == 3


@pytest.mark.asyncio
async def test_resolve_missing_raises_with_flavor_context():
    flavor_id = uuid.uuid4()
    client = _ClientStub([_Item(uuid.uuid4(), "integer")])
    cache = await TypeCache.load(client, flavor_id=flavor_id, flavor_code="postgres14")
    with pytest.raises(TypeNotInFlavorError) as exc:
        cache.resolve("jsonb")
    assert exc.value.code == "jsonb"
    assert exc.value.flavor_code == "postgres14"


@pytest.mark.asyncio
async def test_resolve_missing_without_flavor_code():
    flavor_id = uuid.uuid4()
    client = _ClientStub([])
    cache = await TypeCache.load(client, flavor_id=flavor_id)
    with pytest.raises(TypeNotInFlavorError):
        cache.resolve("integer")
