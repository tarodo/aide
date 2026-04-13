"""Generic filtering and sorting infrastructure for list endpoints."""

import enum
from dataclasses import dataclass
from typing import Any, Callable, Type

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict


class FilterOp(str, enum.Enum):
    """Supported filter operators beyond equality."""

    EQ = "eq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    LIKE = "like"


# Operator suffixes recognised in filter model field names.
_OP_SUFFIXES: set[str] = {op.value for op in FilterOp} - {"eq"}


@dataclass(frozen=True)
class FilterSpec:
    """A structured filter entry carrying an operator."""

    field: str
    op: FilterOp
    value: Any


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

        filter_dict: dict[str, Any] = {}
        for key, value in filters.model_dump().items():  # type: ignore[attr-defined]
            if value is None:
                continue
            # Check for operator suffix (e.g. created_at__gte, name__like)
            parts = key.rsplit("__", 1)
            if len(parts) == 2 and parts[1] in _OP_SUFFIXES:
                field_name, op_str = parts
                op = FilterOp(op_str)
                if op == FilterOp.IN:
                    value = [v.strip() for v in value.split(",") if v.strip()]
                filter_dict[key] = FilterSpec(field=field_name, op=op, value=value)
            else:
                filter_dict[key] = value

        return FilterSortParams(
            page=page,
            size=size,
            filters=filter_dict,
            sort=sort_list,
        )

    return dependency
