from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class BatchCreateRequest(BaseModel, Generic[T]):
    """Request body for batch-create endpoints."""

    items: list[T] = Field(min_length=1)


class BatchCreateResponse(BaseModel, Generic[T]):
    """Response envelope for batch-create endpoints."""

    items: list[T]
    count: int
