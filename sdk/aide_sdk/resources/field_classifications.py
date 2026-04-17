from __future__ import annotations

from typing import List
from uuid import UUID

from pydantic import TypeAdapter

from aide_schemas.field_classification import (
    FieldClassificationCreate,
    FieldClassificationRead,
)
from aide_sdk.resources.base import BaseResource


class FieldClassificationsResource(
    BaseResource[FieldClassificationCreate, FieldClassificationRead, FieldClassificationCreate]
):
    """Append-only resource; update/delete raise NotImplementedError."""

    _path = "/api/v1/field-classifications"
    _read_schema = FieldClassificationRead

    async def update(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError("field_classifications is append-only")

    async def delete(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError("field_classifications is append-only")

    async def get_current(self, field_id: UUID) -> FieldClassificationRead:
        data = await self._http.get(f"{self._path}/current/{field_id}")
        return self._read_adapter.validate_python(data)

    async def list_history(
        self,
        field_id: UUID,
        *,
        page: int = 1,
        size: int = 50,
    ) -> List[FieldClassificationRead]:
        resp = await self.list(
            page=page, size=size, params={"field_id": str(field_id), "sort": "-created_at"}
        )
        return list(resp.items)

    async def list_current_by_dataset(
        self, dataset_id: UUID
    ) -> List[FieldClassificationRead]:
        data = await self._http.get(
            f"{self._path}/by-dataset/{dataset_id}/current"
        )
        adapter: TypeAdapter = TypeAdapter(List[FieldClassificationRead])
        return adapter.validate_python(data)
