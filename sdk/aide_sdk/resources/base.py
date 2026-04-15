from __future__ import annotations

from typing import Any, Generic, Type, TypeVar
from uuid import UUID

from pydantic import BaseModel, TypeAdapter

from aide_sdk.client import HttpClient
from aide_schemas.pagination import Page

CreateT = TypeVar("CreateT", bound=BaseModel)
ReadT = TypeVar("ReadT", bound=BaseModel)
UpdateT = TypeVar("UpdateT", bound=BaseModel)


class BaseResource(Generic[CreateT, ReadT, UpdateT]):
    _path: str
    _read_schema: Type[ReadT]

    def __init__(self, http: HttpClient):
        self._http = http
        self._read_adapter: TypeAdapter[Any] = TypeAdapter(self._read_schema)

    async def list(
        self,
        *,
        page: int = 1,
        size: int = 50,
        params: dict[str, Any] | None = None,
    ) -> Page[ReadT]:
        query: dict[str, Any] = {"page": page, "size": size}
        if params:
            query.update(params)
        data = await self._http.get(self._path, params=query)
        page_adapter: TypeAdapter[Any] = TypeAdapter(Page[self._read_schema])  # type: ignore[name-defined]
        return page_adapter.validate_python(data)

    async def get(self, obj_id: UUID) -> ReadT:
        data = await self._http.get(f"{self._path}/{obj_id}")
        return self._read_adapter.validate_python(data)

    async def create(self, obj_in: CreateT) -> ReadT:
        data = await self._http.post(self._path, json=obj_in.model_dump(mode="json"))
        return self._read_adapter.validate_python(data)

    async def create_many(
        self,
        items: list[CreateT],
        *,
        chunk_size: int = 500,
    ) -> list[ReadT]:
        """Create many objects via batch endpoint, auto-chunking.

        All-or-nothing per chunk. If a mid-sequence chunk fails, earlier
        chunks are already committed server-side; the exception propagates
        and earlier-chunk results are NOT returned.
        """
        if not items:
            return []
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")

        from aide_schemas.batch import BatchCreateResponse

        results: list[ReadT] = []
        response_adapter: TypeAdapter[Any] = TypeAdapter(
            BatchCreateResponse[self._read_schema]  # type: ignore[name-defined]
        )
        for start in range(0, len(items), chunk_size):
            chunk = items[start : start + chunk_size]
            data = await self._http.post(
                f"{self._path}/batch",
                json={"items": [x.model_dump(mode="json") for x in chunk]},
            )
            envelope = response_adapter.validate_python(data)
            results.extend(envelope.items)
        return results

    async def update(self, obj_id: UUID, obj_in: UpdateT) -> ReadT:
        data = await self._http.put(
            f"{self._path}/{obj_id}",
            json=obj_in.model_dump(mode="json", exclude_unset=True),
        )
        return self._read_adapter.validate_python(data)

    async def delete(self, obj_id: UUID) -> ReadT:
        data = await self._http.delete(f"{self._path}/{obj_id}")
        return self._read_adapter.validate_python(data)
