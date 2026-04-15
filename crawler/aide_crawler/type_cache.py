from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from aide_crawler.errors import TypeNotInFlavorError


@dataclass
class TypeCache:
    flavor_code: str | None = None
    _by_code: dict[str, uuid.UUID] = field(default_factory=dict)
    _params_schema_by_code: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    async def load(
        cls,
        client,
        *,
        flavor_id: uuid.UUID,
        flavor_code: str | None = None,
    ) -> "TypeCache":
        cache = cls(flavor_code=flavor_code)
        page_num = 1
        while True:
            resp = await client.data_types.list(
                page=page_num,
                size=100,
                params={"system_flavor_id": str(flavor_id)},
            )
            for item in resp.items:
                cache._by_code[item.code] = item.id
                cache._params_schema_by_code[item.code] = item.params_schema or {}
            if page_num >= resp.pages:
                break
            page_num += 1
        return cache

    def resolve(self, code: str) -> uuid.UUID:
        try:
            return self._by_code[code]
        except KeyError:
            raise TypeNotInFlavorError(code, self.flavor_code) from None

    def allowed_params(self, code: str) -> set[str]:
        return set(self._params_schema_by_code.get(code, {}).keys())

    def __len__(self) -> int:
        return len(self._by_code)
