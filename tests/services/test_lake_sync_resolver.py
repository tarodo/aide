from __future__ import annotations

import uuid

import pytest

from aide_schemas.lake_sync import FieldOverride, LakeSyncWarning
from backend.core import errors
from backend.core.exceptions import AppException
from backend.services.lake_sync_resolver import (
    DataTypeRef,
    SourceTI,
    apply_param_mapping,
    resolve_target_ti,
)

# ---------------- apply_param_mapping ----------------


def test_apply_param_mapping_passthrough() -> None:
    out = apply_param_mapping(
        {"precision": "@precision", "scale": "@scale"},
        {"precision": 10, "scale": 2},
    )
    assert out == {"precision": 10, "scale": 2}


def test_apply_param_mapping_drops_missing_ref() -> None:
    out = apply_param_mapping({"precision": "@precision"}, {})
    assert out == {}


def test_apply_param_mapping_literal() -> None:
    out = apply_param_mapping({"length": 16, "extra": "x"}, {"length": 99})
    assert out == {"length": 16, "extra": "x"}


# ---------------- resolve_target_ti ----------------


def _ref(code: str, params_schema: dict | None = None) -> DataTypeRef:
    return DataTypeRef(
        id=uuid.uuid4(),
        code=code,
        params_schema=params_schema or {},
    )


def test_resolve_leaf_passthrough() -> None:
    src_dt = _ref("bigint")
    tgt_dt = _ref("long")

    src = SourceTI(
        data_type=src_dt,
        type_params={},
        children=[],
    )

    target_lookup_by_code = {"long": tgt_dt, "string": _ref("string")}
    rules_by_source_id = {
        src_dt.id: [
            (tgt_dt, {"params": {}, "safety": "implicit"}),
        ]
    }

    warnings: list[LakeSyncWarning] = []
    out = resolve_target_ti(
        src,
        target_lookup_by_code=target_lookup_by_code,
        rules_by_source_id=rules_by_source_id,
        field_override=None,
        field_name="user_id",
        warnings=warnings,
    )
    assert out.data_type_id == tgt_dt.id
    assert out.type_params == {}
    assert out.children == []
    assert warnings == []


def test_resolve_numeric_to_decimal_with_param_mapping() -> None:
    src_dt = _ref("numeric")
    tgt_dt = _ref(
        "decimal",
        params_schema={
            "precision": {"type": "int", "required": True},
            "scale": {"type": "int", "required": True},
        },
    )

    src = SourceTI(
        data_type=src_dt,
        type_params={"precision": 10, "scale": 2},
        children=[],
    )
    target_lookup_by_code = {"decimal": tgt_dt, "string": _ref("string")}
    rules_by_source_id = {
        src_dt.id: [
            (
                tgt_dt,
                {
                    "params": {"precision": "@precision", "scale": "@scale"},
                    "safety": "safe",
                },
            )
        ]
    }
    warnings: list[LakeSyncWarning] = []
    out = resolve_target_ti(
        src,
        target_lookup_by_code=target_lookup_by_code,
        rules_by_source_id=rules_by_source_id,
        field_override=None,
        field_name="amount",
        warnings=warnings,
    )
    assert out.data_type_id == tgt_dt.id
    assert out.type_params == {"precision": 10, "scale": 2}


def test_resolve_array_to_list_with_slot_rename() -> None:
    pg_array = _ref("array")
    pg_int = _ref("integer")
    ice_list = _ref("list")
    ice_int = _ref("int")

    src = SourceTI(
        data_type=pg_array,
        type_params={},
        children=[
            (
                "item",
                SourceTI(data_type=pg_int, type_params={}, children=[]),
            )
        ],
    )
    target_lookup_by_code = {
        "list": ice_list,
        "int": ice_int,
        "string": _ref("string"),
    }
    rules_by_source_id = {
        pg_array.id: [(ice_list, {"params": {}, "safety": "safe"})],
        pg_int.id: [(ice_int, {"params": {}, "safety": "implicit"})],
    }
    warnings: list[LakeSyncWarning] = []
    out = resolve_target_ti(
        src,
        target_lookup_by_code=target_lookup_by_code,
        rules_by_source_id=rules_by_source_id,
        field_override=None,
        field_name="tags",
        warnings=warnings,
    )
    assert out.data_type_id == ice_list.id
    assert len(out.children) == 1
    slot, child = out.children[0]
    # Source slot was "item"; target list expects "element".
    assert slot == "element"
    assert child.data_type_id == ice_int.id


def test_resolve_zero_rules_falls_back_to_string() -> None:
    src_dt = _ref("xml")
    str_dt = _ref("string")

    src = SourceTI(data_type=src_dt, type_params={}, children=[])
    target_lookup_by_code = {"string": str_dt}
    rules_by_source_id: dict = {}

    warnings: list[LakeSyncWarning] = []
    out = resolve_target_ti(
        src,
        target_lookup_by_code=target_lookup_by_code,
        rules_by_source_id=rules_by_source_id,
        field_override=None,
        field_name="doc",
        warnings=warnings,
    )
    assert out.data_type_id == str_dt.id
    assert any(w.code == "UNSUPPORTED_TYPE_FALLBACK" for w in warnings)


def test_resolve_multiple_rules_raises_ambiguous() -> None:
    src_dt = _ref("numeric")
    decimal_dt = _ref("decimal")
    string_dt = _ref("string")

    src = SourceTI(data_type=src_dt, type_params={}, children=[])
    target_lookup_by_code = {"decimal": decimal_dt, "string": string_dt}
    rules_by_source_id = {
        src_dt.id: [
            (decimal_dt, {"params": {}, "safety": "safe"}),
            (string_dt, {"params": {}, "safety": "unsafe"}),
        ]
    }

    with pytest.raises(AppException) as exc:
        resolve_target_ti(
            src,
            target_lookup_by_code=target_lookup_by_code,
            rules_by_source_id=rules_by_source_id,
            field_override=None,
            field_name="amount",
            warnings=[],
        )
    assert exc.value.error_code == errors.LAKE_SYNC_AMBIGUOUS_CAST
    assert exc.value.details == {
        "field": "amount",
        "candidates": ["decimal", "string"],
    }


def test_resolve_override_skips_rules() -> None:
    src_dt = _ref("numeric")
    decimal_dt = _ref(
        "decimal",
        params_schema={
            "precision": {"type": "int", "required": True},
            "scale": {"type": "int", "required": True},
        },
    )
    string_dt = _ref("string")

    src = SourceTI(
        data_type=src_dt, type_params={"precision": 10, "scale": 2}, children=[]
    )
    target_lookup_by_code = {"decimal": decimal_dt, "string": string_dt}
    rules_by_source_id = {
        src_dt.id: [
            (decimal_dt, {"params": {}, "safety": "safe"}),
        ]
    }
    warnings: list[LakeSyncWarning] = []
    out = resolve_target_ti(
        src,
        target_lookup_by_code=target_lookup_by_code,
        rules_by_source_id=rules_by_source_id,
        field_override=FieldOverride(data_type_code="string"),
        field_name="amount",
        warnings=warnings,
    )
    assert out.data_type_id == string_dt.id
    assert any(w.code == "OVERRIDE_APPLIED" for w in warnings)
