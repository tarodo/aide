from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import types as sa_types

from aide_crawler.errors import UnknownTypeError


@dataclass
class TypeMapping:
    data_type_code: str
    type_params: dict[str, Any]


# Generic SA → postgres14 code map. Order matters: put subclasses before parents
# because isinstance checks run top to bottom.
GENERIC_TYPE_MAP: list[tuple[type, str]] = [
    (sa_types.BigInteger, "bigint"),
    (sa_types.SmallInteger, "smallint"),
    (sa_types.Integer, "integer"),
    (sa_types.Boolean, "boolean"),
    (sa_types.Date, "date"),
    (sa_types.Time, "time"),
    (sa_types.DateTime, "timestamp"),
    (sa_types.Double, "double"),
    (sa_types.Float, "real"),
    (sa_types.Numeric, "numeric"),
    (sa_types.LargeBinary, "bytea"),
    (sa_types.UnicodeText, "text"),
    (sa_types.Text, "text"),
    (sa_types.Unicode, "varchar"),
    (sa_types.String, "varchar"),
    (sa_types.Uuid, "uuid"),
    (sa_types.JSON, "json"),
]

DIALECT_TYPE_MAP: dict[tuple[str, str], str] = {
    ("postgresql", "JSONB"): "jsonb",
    ("postgresql", "JSON"): "json",
    ("postgresql", "UUID"): "uuid",
    ("postgresql", "INET"): "inet",
    ("postgresql", "CIDR"): "cidr",
    ("postgresql", "MACADDR"): "macaddr",
    ("postgresql", "INTERVAL"): "interval",
    ("postgresql", "TSVECTOR"): "tsvector",
    ("postgresql", "BYTEA"): "bytea",
    ("postgresql", "ENUM"): "enum",
}


def _extract_params(sa_type: Any) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if getattr(sa_type, "length", None) is not None:
        params["length"] = sa_type.length
    if getattr(sa_type, "precision", None) is not None:
        params["precision"] = sa_type.precision
    if getattr(sa_type, "scale", None) is not None:
        params["scale"] = sa_type.scale
    return params


def resolve_type(dialect_name: str, sa_type: Any) -> TypeMapping:
    """Map a SQLAlchemy type object to (code, params).

    Raises UnknownTypeError if no mapping is found.
    """
    cls_name = type(sa_type).__name__
    code = DIALECT_TYPE_MAP.get((dialect_name, cls_name))
    if code is None:
        for sa_class, generic_code in GENERIC_TYPE_MAP:
            if isinstance(sa_type, sa_class):
                code = generic_code
                break
    if code is None:
        raise UnknownTypeError(dialect_name, cls_name)
    return TypeMapping(data_type_code=code, type_params=_extract_params(sa_type))
