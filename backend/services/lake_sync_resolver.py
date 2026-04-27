from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from aide_schemas.lake_sync import FieldOverride, LakeSyncWarning
from backend.core import errors
from backend.core.exceptions import AppException
from backend.services.params_schema_validator import validate_type_params

# Slot rename when a source aggregate maps to an Iceberg aggregate with
# a different child-slot convention. Today only pg.array → iceberg.list.
_SLOT_RENAMES_BY_TARGET_CODE: dict[str, dict[str, str]] = {
    "list": {"item": "element"},
}


@dataclass
class DataTypeRef:
    """Lightweight DataType handle preloaded from DB."""

    id: uuid.UUID
    code: str
    params_schema: dict[str, Any]


@dataclass
class SourceTI:
    """Source TypeInstance node, preloaded with its DataType.

    `children` is a list of (slot, child) tuples in source slot space.
    """

    data_type: DataTypeRef
    type_params: dict[str, Any]
    children: list[tuple[str, "SourceTI"]] = field(default_factory=list)


@dataclass
class TargetTI:
    """Plan for a target TypeInstance subtree.

    `children` is a list of (slot, child) tuples in target slot space.
    """

    data_type_id: uuid.UUID
    type_params: dict[str, Any]
    children: list[tuple[str, "TargetTI"]] = field(default_factory=list)


def apply_param_mapping(
    mapping: dict[str, Any], src_params: dict[str, Any]
) -> dict[str, Any]:
    """Translate source type params via a CastRule.param_mapping spec.

    Strings starting with `@` reference a source param key; missing
    references are dropped (target uses its own default). All other
    values are taken literally.
    """
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, str) and value.startswith("@"):
            ref = value[1:]
            if ref in src_params:
                out[key] = src_params[ref]
        else:
            out[key] = value
    return out


def _filter_against_schema(
    params: dict[str, Any], params_schema: dict[str, Any]
) -> dict[str, Any]:
    """Drop unknown keys, then validate via the existing validator.

    Raises AppException(TYPE_INSTANCE_PARAMS_INVALID) on bad input.
    """
    cleaned = {k: v for k, v in params.items() if k in params_schema}
    validate_type_params(params_schema, cleaned)
    return cleaned


def _rename_child_slot(target_code: str, source_slot: str) -> str:
    return _SLOT_RENAMES_BY_TARGET_CODE.get(target_code, {}).get(
        source_slot, source_slot
    )


def resolve_target_ti(
    src: SourceTI,
    *,
    target_lookup_by_code: dict[str, DataTypeRef],
    rules_by_source_id: dict[uuid.UUID, list[tuple[DataTypeRef, dict[str, Any]]]],
    field_override: FieldOverride | None,
    field_name: str,
    warnings: list[LakeSyncWarning],
) -> TargetTI:
    """Compute a target TypeInstance plan from a source subtree.

    Inputs are all preloaded (no DB) — callers are responsible for
    fetching DataTypes and CastRules in batch and indexing them by
    source data_type_id and target code.

    Each rule in `rules_by_source_id[src.data_type.id]` is a tuple of
    (target DataTypeRef, {"params": dict, "safety": str}).
    """
    if field_override is not None:
        target_dt = target_lookup_by_code.get(field_override.data_type_code)
        if target_dt is None:
            raise AppException(errors.DATA_TYPE_NOT_FOUND)
        target_params = _filter_against_schema(
            dict(field_override.type_params or {}), target_dt.params_schema
        )
        warnings.append(
            LakeSyncWarning(
                field_name=field_name,
                code="OVERRIDE_APPLIED",
                detail=f"override → {target_dt.code}",
            )
        )
        # Overrides are leaf-only in MVP — children resolve from source.
        children = _resolve_children(
            src.children,
            target_dt.code,
            target_lookup_by_code=target_lookup_by_code,
            rules_by_source_id=rules_by_source_id,
            field_name=field_name,
            warnings=warnings,
        )
        return TargetTI(
            data_type_id=target_dt.id,
            type_params=target_params,
            children=children,
        )

    rules = rules_by_source_id.get(src.data_type.id, [])

    if len(rules) == 0:
        fallback = target_lookup_by_code.get("string")
        if fallback is None:
            raise AppException(errors.DATA_TYPE_NOT_FOUND)
        warnings.append(
            LakeSyncWarning(
                field_name=field_name,
                code="UNSUPPORTED_TYPE_FALLBACK",
                detail=(
                    f"no CastRule for {src.data_type.code} → iceberg_v2; "
                    "used 'string'"
                ),
            )
        )
        return TargetTI(
            data_type_id=fallback.id,
            type_params={},
            children=[],
        )

    if len(rules) > 1:
        raise AppException(
            errors.LAKE_SYNC_AMBIGUOUS_CAST,
        )

    target_dt, rule_meta = rules[0]
    raw_params = apply_param_mapping(
        dict(rule_meta.get("params") or {}), src.type_params
    )
    target_params = _filter_against_schema(raw_params, target_dt.params_schema)
    children = _resolve_children(
        src.children,
        target_dt.code,
        target_lookup_by_code=target_lookup_by_code,
        rules_by_source_id=rules_by_source_id,
        field_name=field_name,
        warnings=warnings,
    )
    return TargetTI(
        data_type_id=target_dt.id,
        type_params=target_params,
        children=children,
    )


def _resolve_children(
    src_children: list[tuple[str, SourceTI]],
    target_code: str,
    *,
    target_lookup_by_code: dict[str, DataTypeRef],
    rules_by_source_id: dict[uuid.UUID, list[tuple[DataTypeRef, dict[str, Any]]]],
    field_name: str,
    warnings: list[LakeSyncWarning],
) -> list[tuple[str, TargetTI]]:
    out: list[tuple[str, TargetTI]] = []
    for slot, child in src_children:
        target_slot = _rename_child_slot(target_code, slot)
        child_target = resolve_target_ti(
            child,
            target_lookup_by_code=target_lookup_by_code,
            rules_by_source_id=rules_by_source_id,
            field_override=None,
            field_name=f"{field_name}.{slot}",
            warnings=warnings,
        )
        out.append((target_slot, child_target))
    return out
