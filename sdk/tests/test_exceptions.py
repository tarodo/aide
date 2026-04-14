import pytest

from aide_sdk.exceptions import (
    AuthError,
    ConflictError,
    NotFoundError,
    ValidationError,
    raise_for_status,
)


def test_raise_for_status_200_no_exception():
    raise_for_status(200, "OK", "success")


def test_raise_for_status_404_not_found():
    with pytest.raises(NotFoundError) as exc_info:
        raise_for_status(404, "NOT_FOUND", "not found")
    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "NOT_FOUND"


def test_raise_for_status_401_auth_error():
    with pytest.raises(AuthError):
        raise_for_status(401, "UNAUTHORIZED", "bad token")


def test_raise_for_status_409_conflict():
    with pytest.raises(ConflictError):
        raise_for_status(409, "VERSION_CONFLICT", "version mismatch")


def test_raise_for_status_422_validation():
    with pytest.raises(ValidationError):
        raise_for_status(422, "VALIDATION", "invalid input")
