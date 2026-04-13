import pytest
from fastapi import HTTPException

from backend.api.filter_sort import parse_sort

ALLOWED = {"code", "name", "created_at"}


class TestParseSort:
    def test_none_returns_default(self):
        result = parse_sort(None, ALLOWED, "code")
        assert result == [("code", False)]

    def test_empty_string_returns_default(self):
        result = parse_sort("", ALLOWED, "code")
        assert result == [("code", False)]

    def test_single_field_asc(self):
        result = parse_sort("name", ALLOWED, "code")
        assert result == [("name", False)]

    def test_single_field_desc(self):
        result = parse_sort("-created_at", ALLOWED, "code")
        assert result == [("created_at", True)]

    def test_multi_field(self):
        result = parse_sort("-created_at,code", ALLOWED, "code")
        assert result == [("created_at", True), ("code", False)]

    def test_multi_field_with_spaces(self):
        result = parse_sort(" -name , code ", ALLOWED, "code")
        assert result == [("name", True), ("code", False)]

    def test_invalid_field_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            parse_sort("hacked_field", ALLOWED, "code")
        assert exc_info.value.status_code == 422
        assert "hacked_field" in str(exc_info.value.detail)

    def test_one_valid_one_invalid_raises_422(self):
        with pytest.raises(HTTPException):
            parse_sort("code,bad_field", ALLOWED, "code")
