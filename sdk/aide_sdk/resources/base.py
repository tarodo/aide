from __future__ import annotations

from typing import Any, Generic, Type, TypeVar
from uuid import UUID

from pydantic import BaseModel

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
        return Page[self._read_schema].model_validate(data)  # type: ignore[name-defined]

    async def get(self, obj_id: UUID) -> ReadT:
        data = await self._http.get(f"{self._path}/{obj_id}")
        return self._read_schema.model_validate(data)

    async def create(self, obj_in: CreateT) -> ReadT:
        data = await self._http.post(self._path, json=obj_in.model_dump(mode="json"))
        return self._read_schema.model_validate(data)

    async def update(self, obj_id: UUID, obj_in: UpdateT) -> ReadT:
        data = await self._http.put(
            f"{self._path}/{obj_id}",
            json=obj_in.model_dump(mode="json", exclude_unset=True),
        )
        return self._read_schema.model_validate(data)

    async def delete(self, obj_id: UUID) -> ReadT:
        data = await self._http.delete(f"{self._path}/{obj_id}")
        return self._read_schema.model_validate(data)
