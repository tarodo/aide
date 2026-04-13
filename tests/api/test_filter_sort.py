import pytest
from fastapi import HTTPException

from backend.api.filter_sort import FilterOp, FilterSpec, _OP_SUFFIXES, parse_sort

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


# ---------------------------------------------------------------------------
# FilterOp / FilterSpec
# ---------------------------------------------------------------------------


class TestFilterOp:
    def test_all_ops_in_suffix_set(self):
        """Every op except 'eq' should be in the recognised suffix set."""
        for op in FilterOp:
            if op == FilterOp.EQ:
                assert op.value not in _OP_SUFFIXES
            else:
                assert op.value in _OP_SUFFIXES

    def test_filter_spec_frozen(self):
        spec = FilterSpec(field="name", op=FilterOp.LIKE, value="prod")
        with pytest.raises(AttributeError):
            spec.field = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Dependency parsing logic  (unit-test via helper)
# ---------------------------------------------------------------------------


def _parse_filters(raw: dict[str, object]) -> dict[str, object]:
    """Simulate the parsing logic from get_filter_sort_dependency."""
    result: dict[str, object] = {}
    for key, value in raw.items():
        if value is None:
            continue
        parts = key.rsplit("__", 1)
        if len(parts) == 2 and parts[1] in _OP_SUFFIXES:
            field_name, op_str = parts
            op = FilterOp(op_str)
            if op == FilterOp.IN:
                value = [v.strip() for v in value.split(",") if v.strip()]  # type: ignore[union-attr]
            result[key] = FilterSpec(field=field_name, op=op, value=value)
        else:
            result[key] = value
    return result


class TestFilterParsing:
    def test_plain_equality_unchanged(self):
        result = _parse_filters({"code": "foo"})
        assert result == {"code": "foo"}

    def test_none_values_stripped(self):
        result = _parse_filters({"code": None, "name__like": None})
        assert result == {}

    def test_gte_produces_filter_spec(self):
        result = _parse_filters({"created_at__gte": "2024-01-01"})
        spec = result["created_at__gte"]
        assert isinstance(spec, FilterSpec)
        assert spec.field == "created_at"
        assert spec.op == FilterOp.GTE
        assert spec.value == "2024-01-01"

    def test_lte_produces_filter_spec(self):
        result = _parse_filters({"created_at__lte": "2024-12-31"})
        spec = result["created_at__lte"]
        assert isinstance(spec, FilterSpec)
        assert spec.op == FilterOp.LTE

    def test_gt_produces_filter_spec(self):
        result = _parse_filters({"created_at__gt": "2024-06-01"})
        assert result["created_at__gt"].op == FilterOp.GT

    def test_lt_produces_filter_spec(self):
        result = _parse_filters({"created_at__lt": "2024-06-01"})
        assert result["created_at__lt"].op == FilterOp.LT

    def test_like_produces_filter_spec(self):
        result = _parse_filters({"name__like": "prod"})
        spec = result["name__like"]
        assert spec.field == "name"
        assert spec.op == FilterOp.LIKE
        assert spec.value == "prod"

    def test_in_splits_csv(self):
        result = _parse_filters({"kind__in": "raw, staging, curated"})
        spec = result["kind__in"]
        assert spec.op == FilterOp.IN
        assert spec.value == ["raw", "staging", "curated"]

    def test_in_single_value(self):
        result = _parse_filters({"kind__in": "raw"})
        assert result["kind__in"].value == ["raw"]

    def test_in_strips_empty_entries(self):
        result = _parse_filters({"kind__in": "raw,,, staging,"})
        assert result["kind__in"].value == ["raw", "staging"]

    def test_mixed_equality_and_operators(self):
        result = _parse_filters(
            {
                "code": "prod",
                "code__like": "pro",
                "created_at__gte": "2024-01-01",
            }
        )
        assert result["code"] == "prod"
        assert isinstance(result["code__like"], FilterSpec)
        assert isinstance(result["created_at__gte"], FilterSpec)

    def test_field_with_double_underscore_not_op(self):
        """A field like 'some__thing' where 'thing' is not an op stays plain."""
        result = _parse_filters({"some__thing": "val"})
        assert result == {"some__thing": "val"}
