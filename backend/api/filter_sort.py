"""Generic filtering and sorting infrastructure for list endpoints."""

from dataclasses import dataclass
from typing import Any, Callable, Type

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict


class BaseFilter(BaseModel):
    """Base filter model. Entity-specific filters subclass this.

    Uses extra="forbid" to reject unknown query params (whitelist).
    """

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class FilterSortParams:
    """Validated filter + sort + pagination params passed through layers."""

    page: int
    size: int
    filters: dict[str, Any]
    sort: list[tuple[str, bool]]  # (field_name, is_descending)


def parse_sort(
    raw: str | None,
    allowed: set[str],
    default: str,
) -> list[tuple[str, bool]]:
    """Parse and validate sort string.

    Supports multi-field: "-created_at,code"
    Prefix "-" means DESC.
    """
    if not raw:
        return [(default, False)]

    result: list[tuple[str, bool]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        desc = part.startswith("-")
        field = part.lstrip("-")
        if field not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot sort by '{field}'. Allowed: {sorted(allowed)}",
            )
        result.append((field, desc))

    return result if result else [(default, False)]


def get_filter_sort_dependency(
    filter_model: Type[BaseFilter],
    sortable_fields: set[str],
    default_sort: str = "id",
) -> Callable[..., FilterSortParams]:
    """Factory that produces a FastAPI dependency combining pagination + filter + sort."""

    def dependency(
        page: int = Query(1, ge=1),
        size: int = Query(50, ge=1, le=100),
        sort: str | None = Query(
            None,
            description="Sort field. Prefix with - for DESC. Multi-field: -created_at,code",
        ),
        filters: filter_model = Depends(),  # type: ignore[valid-type]
    ) -> FilterSortParams:
        sort_list = parse_sort(sort, sortable_fields, default_sort)
        filter_dict = {
            k: v for k, v in filters.model_dump().items() if v is not None  # type: ignore[attr-defined]
        }
        return FilterSortParams(
            page=page,
            size=size,
            filters=filter_dict,
            sort=sort_list,
        )

    return dependency
