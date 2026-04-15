import pytest
from sqlalchemy import types as sa_types
from sqlalchemy.dialects import postgresql as pg

from aide_crawler.errors import UnknownTypeError
from aide_crawler.type_map import TypeNode, resolve_type


@pytest.mark.parametrize(
    "sa_type,expected_code",
    [
        (sa_types.SmallInteger(), "smallint"),
        (sa_types.Integer(), "integer"),
        (sa_types.BigInteger(), "bigint"),
        (sa_types.Numeric(10, 2), "numeric"),
        (sa_types.Float(), "real"),
        (sa_types.Double(), "double"),
        (sa_types.String(50), "varchar"),
        (sa_types.Text(), "text"),
        (sa_types.Boolean(), "boolean"),
        (sa_types.Date(), "date"),
        (sa_types.Time(), "time"),
        (sa_types.DateTime(), "timestamp"),
        (sa_types.LargeBinary(), "bytea"),
        (sa_types.Uuid(), "uuid"),
        (sa_types.CHAR(5), "char"),
        (pg.JSONB(), "jsonb"),
        (pg.JSON(), "json"),
        (pg.INET(), "inet"),
        (pg.CIDR(), "cidr"),
        (pg.MACADDR(), "macaddr"),
        (pg.MACADDR8(), "macaddr8"),
        (pg.INTERVAL(), "interval"),
        (pg.TSVECTOR(), "tsvector"),
        (pg.TSQUERY(), "tsquery"),
        (pg.BYTEA(), "bytea"),
        (pg.MONEY(), "money"),
        (pg.OID(), "oid"),
        (pg.INT4RANGE(), "int4range"),
        (pg.INT8RANGE(), "int8range"),
        (pg.NUMRANGE(), "numrange"),
        (pg.TSRANGE(), "tsrange"),
        (pg.TSTZRANGE(), "tstzrange"),
        (pg.DATERANGE(), "daterange"),
    ],
)
def test_resolve_known_leaf_types(sa_type, expected_code):
    node = resolve_type("postgresql", sa_type)
    assert isinstance(node, TypeNode)
    assert node.data_type_code == expected_code
    assert node.children == []


def test_numeric_params_extracted():
    node = resolve_type("postgresql", sa_types.Numeric(14, 4))
    assert node.type_params == {"precision": 14, "scale": 4}


def test_varchar_length_extracted():
    node = resolve_type("postgresql", sa_types.String(255))
    assert node.type_params == {"length": 255}


def test_char_distinguished_from_varchar():
    node = resolve_type("postgresql", sa_types.CHAR(10))
    assert node.data_type_code == "char"
    assert node.type_params == {"length": 10}


def test_text_has_no_params():
    node = resolve_type("postgresql", sa_types.Text())
    assert node.type_params == {}


def test_time_with_timezone_maps_to_timetz():
    plain = resolve_type("postgresql", sa_types.Time())
    tz = resolve_type("postgresql", sa_types.Time(timezone=True))
    assert plain.data_type_code == "time"
    assert tz.data_type_code == "timetz"


def test_timestamp_with_timezone_maps_to_timestamptz():
    plain = resolve_type("postgresql", sa_types.DateTime())
    tz = resolve_type("postgresql", sa_types.DateTime(timezone=True))
    assert plain.data_type_code == "timestamp"
    assert tz.data_type_code == "timestamptz"


def test_bit_fixed_vs_varying():
    fixed = resolve_type("postgresql", pg.BIT(8))
    varying = resolve_type("postgresql", pg.BIT(8, varying=True))
    assert fixed.data_type_code == "bit"
    assert fixed.type_params == {"length": 8}
    assert varying.data_type_code == "varbit"
    assert varying.type_params == {"length": 8}


def test_array_of_integer_builds_two_level_tree():
    node = resolve_type("postgresql", sa_types.ARRAY(sa_types.Integer()))
    assert node.data_type_code == "array"
    assert node.type_params == {}
    assert len(node.children) == 1
    child = node.children[0]
    assert child.slot == "item"
    assert child.node.data_type_code == "integer"
    assert child.node.children == []


def test_array_of_varchar_propagates_length_to_child():
    node = resolve_type("postgresql", sa_types.ARRAY(sa_types.String(64)))
    child = node.children[0].node
    assert child.data_type_code == "varchar"
    assert child.type_params == {"length": 64}


def test_unknown_type_raises_with_repr():
    class Mystery:
        def __repr__(self) -> str:
            return "Mystery()"

    with pytest.raises(UnknownTypeError) as exc:
        resolve_type("postgresql", Mystery())
    assert "Mystery()" in str(exc.value)
