from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """
    Generic pagination response schema.
    """

    items: list[T]
    total: int
    page: int
    size: int
    pages: int
