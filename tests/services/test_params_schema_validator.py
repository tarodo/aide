import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.services.params_schema_validator import validate_type_params

NUMERIC_SCHEMA = {
    "precision": {"type": "int", "required": False, "min": 1, "max": 1000},
    "scale": {"type": "int", "required": False, "min": -1000, "max": 1000},
}

REQUIRED_LENGTH_SCHEMA = {
    "length": {"type": "int", "required": True, "min": 1},
}


def test_none_params_allowed_for_empty_schema():
    validate_type_params({}, None)


def test_empty_params_allowed_for_schema_without_required():
    validate_type_params(NUMERIC_SCHEMA, {})
    validate_type_params(NUMERIC_SCHEMA, None)


def test_required_missing_raises():
    with pytest.raises(AppException) as e:
        validate_type_params(REQUIRED_LENGTH_SCHEMA, {})
    assert e.value.error_code == errors.TYPE_INSTANCE_PARAMS_INVALID


def test_required_null_raises():
    with pytest.raises(AppException) as e:
        validate_type_params(REQUIRED_LENGTH_SCHEMA, {"length": None})
    assert e.value.error_code == errors.TYPE_INSTANCE_PARAMS_INVALID


def test_unknown_key_raises():
    with pytest.raises(AppException):
        validate_type_params(NUMERIC_SCHEMA, {"bogus": 1})


def test_type_mismatch_raises():
    with pytest.raises(AppException):
        validate_type_params(NUMERIC_SCHEMA, {"precision": "oops"})


def test_bool_is_not_int():
    # bool is a subclass of int in Python; validator must reject bool for int param.
    with pytest.raises(AppException):
        validate_type_params(NUMERIC_SCHEMA, {"precision": True})


def test_min_raises_below_bound():
    with pytest.raises(AppException):
        validate_type_params(NUMERIC_SCHEMA, {"precision": 0})


def test_max_raises_above_bound():
    with pytest.raises(AppException):
        validate_type_params(NUMERIC_SCHEMA, {"precision": 1001})


def test_happy_path_numeric():
    validate_type_params(NUMERIC_SCHEMA, {"precision": 10, "scale": 2})


def test_optional_key_null_allowed():
    validate_type_params(NUMERIC_SCHEMA, {"precision": None})
