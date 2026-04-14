from sqlalchemy import types as sa_types

from aide_crawler.type_map import resolve_type


def test_resolve_varchar():
    result = resolve_type("postgresql", sa_types.String(length=255))
    assert result is not None
    assert result.data_type_code == "varchar"
    assert result.type_params == {"length": 255}


def test_resolve_numeric_with_precision_scale():
    result = resolve_type("postgresql", sa_types.Numeric(precision=10, scale=2))
    assert result is not None
    assert result.data_type_code == "numeric"
    assert result.type_params == {"precision": 10, "scale": 2}


def test_resolve_integer_no_params():
    result = resolve_type("postgresql", sa_types.Integer())
    assert result is not None
    assert result.data_type_code == "integer"
    assert result.type_params == {}


def test_resolve_boolean():
    result = resolve_type("postgresql", sa_types.Boolean())
    assert result is not None
    assert result.data_type_code == "boolean"


def test_resolve_unknown_type_returns_none():
    class CustomType(sa_types.TypeEngine):
        pass

    result = resolve_type("postgresql", CustomType())
    assert result is None
