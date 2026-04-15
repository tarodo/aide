from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import types as sa_types
from sqlalchemy.dialects import postgresql as pg

from aide_crawler.errors import UnknownTypeError

ARRAY_ITEM_SLOT = "item"


@dataclass
class TypeNode:
    data_type_code: str
    type_params: dict[str, Any]
    children: list["TypeChild"] = field(default_factory=list)


@dataclass
class TypeChild:
    slot: str
    node: TypeNode


# Generic SA → postgres14 code map. Order matters: subclasses before parents.
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
    (sa_types.CHAR, "char"),
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
    ("postgresql", "MACADDR8"): "macaddr8",
    ("postgresql", "INTERVAL"): "interval",
    ("postgresql", "TSVECTOR"): "tsvector",
    ("postgresql", "TSQUERY"): "tsquery",
    ("postgresql", "BYTEA"): "bytea",
    ("postgresql", "ENUM"): "enum",
    ("postgresql", "MONEY"): "money",
    ("postgresql", "OID"): "oid",
    ("postgresql", "INT4RANGE"): "int4range",
    ("postgresql", "INT8RANGE"): "int8range",
    ("postgresql", "NUMRANGE"): "numrange",
    ("postgresql", "TSRANGE"): "tsrange",
    ("postgresql", "TSTZRANGE"): "tstzrange",
    ("postgresql", "DATERANGE"): "daterange",
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


def resolve_type(dialect_name: str, sa_type: Any) -> TypeNode:
    """Map a SQLAlchemy type object to a TypeNode tree.

    Raises UnknownTypeError if no mapping is found for a leaf type.
    """
    # ARRAY is recursive; do it before any flat lookup.
    if isinstance(sa_type, sa_types.ARRAY):
        item_node = resolve_type(dialect_name, sa_type.item_type)
        return TypeNode(
            data_type_code="array",
            type_params={},
            children=[TypeChild(slot=ARRAY_ITEM_SLOT, node=item_node)],
        )

    # PG BIT branches on .varying; not amenable to the flat dialect map.
    if dialect_name == "postgresql" and isinstance(sa_type, pg.BIT):
        bit_code = "varbit" if getattr(sa_type, "varying", False) else "bit"
        return TypeNode(data_type_code=bit_code, type_params=_extract_params(sa_type))

    # Timezone-aware time/timestamp special-case (PG only).
    if dialect_name == "postgresql":
        if isinstance(sa_type, sa_types.DateTime) and getattr(
            sa_type, "timezone", False
        ):
            return TypeNode(
                data_type_code="timestamptz", type_params=_extract_params(sa_type)
            )
        if isinstance(sa_type, sa_types.Time) and getattr(sa_type, "timezone", False):
            return TypeNode(
                data_type_code="timetz", type_params=_extract_params(sa_type)
            )

    cls_name = type(sa_type).__name__
    code: str | None = DIALECT_TYPE_MAP.get((dialect_name, cls_name))
    if code is None:
        for sa_class, generic_code in GENERIC_TYPE_MAP:
            if isinstance(sa_type, sa_class):
                code = generic_code
                break
    if code is None:
        raise UnknownTypeError(dialect_name, sa_type)
    return TypeNode(data_type_code=code, type_params=_extract_params(sa_type))
