from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import types as sa_types

logger = logging.getLogger(__name__)


@dataclass
class TypeMapping:
    data_type_code: str
    type_params: dict[str, Any]


GENERIC_TYPE_MAP: dict[type, str] = {
    sa_types.BigInteger: "bigint",
    sa_types.Boolean: "boolean",
    sa_types.Date: "date",
    sa_types.DateTime: "timestamp",
    sa_types.Double: "double",
    sa_types.Float: "float",
    sa_types.Integer: "integer",
    sa_types.SmallInteger: "smallint",
    sa_types.String: "varchar",
    sa_types.Text: "text",
    sa_types.Time: "time",
    sa_types.Unicode: "varchar",
    sa_types.UnicodeText: "text",
    sa_types.Uuid: "uuid",
    sa_types.Numeric: "numeric",
    sa_types.LargeBinary: "bytea",
    sa_types.JSON: "json",
    sa_types.ARRAY: "array",
}

DIALECT_TYPE_MAP: dict[tuple[str, str], str] = {
    ("postgresql", "JSONB"): "jsonb",
    ("postgresql", "UUID"): "uuid",
    ("postgresql", "INET"): "inet",
    ("postgresql", "CIDR"): "cidr",
    ("postgresql", "MACADDR"): "macaddr",
    ("postgresql", "INTERVAL"): "interval",
    ("postgresql", "TSVECTOR"): "tsvector",
    ("postgresql", "BYTEA"): "bytea",
    ("postgresql", "ENUM"): "enum",
    ("mysql", "TINYINT"): "tinyint",
    ("mysql", "MEDIUMINT"): "mediumint",
    ("mysql", "YEAR"): "year",
    ("mysql", "ENUM"): "enum",
    ("mysql", "SET"): "set",
}


def resolve_type(dialect_name: str, sa_type: Any) -> TypeMapping | None:
    """
    Map a SQLAlchemy type object to a DataType code and extracted parameters.
    Returns None if type is unknown.
    """
    type_class_name = type(sa_type).__name__

    code = DIALECT_TYPE_MAP.get((dialect_name, type_class_name))

    if code is None:
        for sa_class, generic_code in GENERIC_TYPE_MAP.items():
            if isinstance(sa_type, sa_class):
                code = generic_code
                break

    if code is None:
        logger.warning(
            "Unknown SQL type: dialect=%s type=%s", dialect_name, type_class_name
        )
        return None

    params: dict[str, Any] = {}
    if hasattr(sa_type, "length") and sa_type.length is not None:
        params["length"] = sa_type.length
    if hasattr(sa_type, "precision") and sa_type.precision is not None:
        params["precision"] = sa_type.precision
    if hasattr(sa_type, "scale") and sa_type.scale is not None:
        params["scale"] = sa_type.scale

    return TypeMapping(data_type_code=code, type_params=params)
