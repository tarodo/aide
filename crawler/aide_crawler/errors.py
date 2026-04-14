from __future__ import annotations


class CrawlerError(Exception):
    """Base class for crawler-specific errors."""


class UnknownTypeError(CrawlerError):
    def __init__(self, dialect: str, sa_class_name: str):
        super().__init__(
            f"Unknown SQL type: dialect={dialect} sa_class={sa_class_name}"
        )
        self.dialect = dialect
        self.sa_class_name = sa_class_name


class TypeNotInFlavorError(CrawlerError):
    def __init__(self, code: str, flavor_code: str | None = None):
        ctx = f" flavor={flavor_code}" if flavor_code else ""
        super().__init__(f"DataType code '{code}' not found in metastore{ctx}")
        self.code = code
        self.flavor_code = flavor_code
