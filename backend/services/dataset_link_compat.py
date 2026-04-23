"""Compatibility service for DatasetLink.

Pure algorithm (compute_field_compat_issues) plus the I/O wrapper
(DatasetLinkCompatService.compat_report) live here. The algorithm accepts
pre-resolved rows so it is trivially unit-testable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from aide_schemas.cast_rule import CastSafety
from aide_schemas.lineage_compat import FieldCompatIssue


@dataclass
class CompatInputs:
    """Inputs for per-FieldLink compat computation.

    target_field_origin — string value of Field.origin ("mapped"/"tech"/"deprecated")
    source_binding / target_binding — dicts or None. When non-None must contain
        nested `type_instance` dict with `id`, `data_type_id`, `type_params`,
        plus top-level `is_nullable: bool`.
    cast_rule — dict with `id` and `safety` (cast-rule safety enum value), or None.
    """

    target_field_origin: str
    source_binding: dict[str, Any] | None
    target_binding: dict[str, Any] | None
    cast_rule: dict[str, Any] | None


def compute_field_compat_issues(inputs: CompatInputs) -> list[FieldCompatIssue]:
    issues: list[FieldCompatIssue] = []

    # Defensive: FieldLink should not exist against non-MAPPED target.
    if inputs.target_field_origin != "mapped":
        return issues

    if inputs.source_binding is None:
        issues.append(FieldCompatIssue.SOURCE_UNBOUND)
        return issues
    if inputs.target_binding is None:
        issues.append(FieldCompatIssue.TARGET_UNBOUND)
        return issues

    src_ti_id: uuid.UUID = inputs.source_binding["type_instance"]["id"]
    tgt_ti_id: uuid.UUID = inputs.target_binding["type_instance"]["id"]

    if src_ti_id != tgt_ti_id:
        rule = inputs.cast_rule
        if rule is None:
            issues.append(FieldCompatIssue.TYPE_INCOMPATIBLE)
        else:
            safety = rule["safety"]
            if safety == CastSafety.IMPLICIT.value:
                pass  # exact compat via implicit cast
            elif safety == CastSafety.SAFE.value:
                issues.append(FieldCompatIssue.TYPE_NEEDS_CAST)
            elif safety == CastSafety.UNSAFE.value:
                issues.append(FieldCompatIssue.TYPE_UNSAFE_CAST)
            else:
                # Unknown safety — conservatively treat as incompatible.
                issues.append(FieldCompatIssue.TYPE_INCOMPATIBLE)

    if (
        inputs.source_binding.get("is_nullable") is True
        and inputs.target_binding.get("is_nullable") is False
    ):
        issues.append(FieldCompatIssue.NULLABILITY_WARN)

    return issues
