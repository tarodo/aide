import pytest
from sqlalchemy import types as sa_types
from sqlalchemy.dialects import postgresql as pg

from aide_crawler.errors import UnknownTypeError
from aide_crawler.type_map import resolve_type


@pytest.mark.parametrize(
    "sa_type,dialect,expected_code",
    [
        (sa_types.SmallInteger(), "postgresql", "smallint"),
        (sa_types.Integer(), "postgresql", "integer"),
        (sa_types.BigInteger(), "postgresql", "bigint"),
        (sa_types.Numeric(10, 2), "postgresql", "numeric"),
        (sa_types.Float(), "postgresql", "real"),
        (sa_types.Double(), "postgresql", "double"),
        (sa_types.String(50), "postgresql", "varchar"),
        (sa_types.Text(), "postgresql", "text"),
        (sa_types.Boolean(), "postgresql", "boolean"),
        (sa_types.Date(), "postgresql", "date"),
        (sa_types.Time(), "postgresql", "time"),
        (sa_types.DateTime(), "postgresql", "timestamp"),
        (sa_types.LargeBinary(), "postgresql", "bytea"),
        (sa_types.Uuid(), "postgresql", "uuid"),
        (pg.JSONB(), "postgresql", "jsonb"),
        (pg.JSON(), "postgresql", "json"),
        (pg.INET(), "postgresql", "inet"),
        (pg.CIDR(), "postgresql", "cidr"),
        (pg.MACADDR(), "postgresql", "macaddr"),
        (pg.INTERVAL(), "postgresql", "interval"),
        (pg.TSVECTOR(), "postgresql", "tsvector"),
        (pg.BYTEA(), "postgresql", "bytea"),
    ],
)
def test_resolve_known_types(sa_type, dialect, expected_code):
    mapping = resolve_type(dialect, sa_type)
    assert mapping.data_type_code == expected_code


def test_numeric_params_extracted():
    mapping = resolve_type("postgresql", sa_types.Numeric(14, 4))
    assert mapping.type_params == {"precision": 14, "scale": 4}


def test_varchar_length_extracted():
    mapping = resolve_type("postgresql", sa_types.String(255))
    assert mapping.type_params == {"length": 255}


def test_text_has_no_params():
    mapping = resolve_type("postgresql", sa_types.Text())
    assert mapping.type_params == {}


def test_unknown_type_raises():
    class Mystery:
        pass

    with pytest.raises(UnknownTypeError):
        resolve_type("postgresql", Mystery())
