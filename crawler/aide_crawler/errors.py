from __future__ import annotations

from typing import Any


class CrawlerError(Exception):
    """Base class for crawler-specific errors."""


class UnknownTypeError(CrawlerError):
    def __init__(self, dialect: str, sa_type: Any):
        super().__init__(f"Unknown SQL type: dialect={dialect} sa_type={sa_type!r}")
        self.dialect = dialect
        self.sa_type = sa_type
        self.sa_class_name = type(sa_type).__name__


class TypeNotInFlavorError(CrawlerError):
    def __init__(self, code: str, flavor_code: str | None = None):
        ctx = f" flavor={flavor_code}" if flavor_code else ""
        super().__init__(f"DataType code '{code}' not found in metastore{ctx}")
        self.code = code
        self.flavor_code = flavor_code
