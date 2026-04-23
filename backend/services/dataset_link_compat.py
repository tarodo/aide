"""Compatibility service for DatasetLink.

Pure algorithm (compute_field_compat_issues) plus the I/O wrapper
(DatasetLinkCompatService.compat_report) live here. The algorithm accepts
pre-resolved rows so it is trivially unit-testable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from aide_schemas.cast_rule import CastSafety
from aide_schemas.lineage_compat import FieldCompatIssue
from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.cast_rule import CastRule
from backend.models.dataset_link import DatasetLink as DatasetLinkModel
from backend.models.field_binding import FieldBinding as FieldBindingModel
from backend.models.field_link import FieldLink as FieldLinkModel
from backend.models.type_instance import TypeInstance as TypeInstanceModel
from backend.schemas.lineage_compat import (
    CompatSeverity,
    CompatSummary,
    DatasetLinkCompatReport,
    FieldCompatFieldRef,
    FieldCompatRow,
    PinDrift,
    PinDriftSide,
)


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


_ERROR_ISSUES = {
    FieldCompatIssue.SOURCE_UNBOUND,
    FieldCompatIssue.TARGET_UNBOUND,
    FieldCompatIssue.TYPE_INCOMPATIBLE,
    FieldCompatIssue.TYPE_UNSAFE_CAST,
}
_WARN_ISSUES = {
    FieldCompatIssue.TYPE_NEEDS_CAST,
    FieldCompatIssue.NULLABILITY_WARN,
}


def _severity_of_issues(issues: list[FieldCompatIssue]) -> CompatSeverity:
    if not issues:
        return CompatSeverity.OK
    if any(i in _ERROR_ISSUES for i in issues):
        return CompatSeverity.ERROR
    return CompatSeverity.WARN


def _render_type(binding: FieldBindingModel | None) -> str | None:
    if binding is None:
        return None
    dt_code = binding.type_instance.data_type.code
    params = binding.type_instance.type_params or {}
    if params:
        formatted = ",".join(str(v) for v in params.values())
        return f"{dt_code}({formatted})"
    return dt_code


def _binding_to_dict(binding: FieldBindingModel | None) -> dict[str, Any] | None:
    if binding is None:
        return None
    return {
        "id": binding.id,
        "type_instance": {
            "id": binding.type_instance.id,
            "data_type_id": binding.type_instance.data_type_id,
            "type_params": binding.type_instance.type_params or {},
        },
        "type_instance_id": binding.type_instance_id,
        "is_nullable": binding.is_nullable,
    }


async def _load_field_binding_eager(
    uow: UnitOfWork, field_id: uuid.UUID, dataset_schema_id: uuid.UUID
) -> FieldBindingModel | None:
    """Fetch FieldBinding with type_instance and data_type eager-loaded.

    Avoids MissingGreenlet errors in async code paths that touch
    `binding.type_instance.data_type.code` downstream.
    """
    stmt = (
        select(FieldBindingModel)
        .where(
            FieldBindingModel.field_id == field_id,
            FieldBindingModel.dataset_schema_id == dataset_schema_id,
        )
        .options(
            selectinload(FieldBindingModel.type_instance).selectinload(
                TypeInstanceModel.data_type
            )
        )
    )
    result = await uow.session.execute(stmt)
    return result.scalars().first()


class DatasetLinkCompatService:
    async def compat_report(
        self, uow: UnitOfWork, dataset_link_id: uuid.UUID
    ) -> DatasetLinkCompatReport:
        async with uow:
            link = await uow.session.get(DatasetLinkModel, dataset_link_id)
            if link is None or link.deleted_at is not None:
                raise AppException(errors.DATASET_LINK_NOT_FOUND)

            src_latest = await uow.dataset_schemas.latest_for_dataset(
                link.source_dataset_id
            )
            tgt_latest = await uow.dataset_schemas.latest_for_dataset(
                link.target_dataset_id
            )
            src_pinned = await uow.dataset_schemas.get(link.source_schema_id)
            tgt_pinned = await uow.dataset_schemas.get(link.target_schema_id)
            # Pinned schemas are NOT NULL FKs on DatasetLink — must exist.
            assert src_pinned is not None
            assert tgt_pinned is not None

            pin_drift = PinDrift(
                source=PinDriftSide(
                    pinned_version=src_pinned.version_num,
                    latest_version=(
                        src_latest.version_num if src_latest else src_pinned.version_num
                    ),
                    has_drift=(
                        src_latest is not None
                        and src_latest.version_num != src_pinned.version_num
                    ),
                ),
                target=PinDriftSide(
                    pinned_version=tgt_pinned.version_num,
                    latest_version=(
                        tgt_latest.version_num if tgt_latest else tgt_pinned.version_num
                    ),
                    has_drift=(
                        tgt_latest is not None
                        and tgt_latest.version_num != tgt_pinned.version_num
                    ),
                ),
            )

            stmt = select(FieldLinkModel).where(
                FieldLinkModel.dataset_link_id == dataset_link_id
            )
            result = await uow.session.execute(stmt)
            field_links = list(result.scalars())

            field_compat: list[FieldCompatRow] = []
            ok_count = warn_count = error_count = 0

            for fl in field_links:
                src_field = await uow.fields.get(fl.source_field_id)
                tgt_field = await uow.fields.get(fl.target_field_id)
                if src_field is None or tgt_field is None:
                    continue

                src_binding = await _load_field_binding_eager(
                    uow, fl.source_field_id, link.source_schema_id
                )
                tgt_binding = await _load_field_binding_eager(
                    uow, fl.target_field_id, link.target_schema_id
                )

                cast_rule = None
                if (
                    src_binding is not None
                    and tgt_binding is not None
                    and src_binding.type_instance_id != tgt_binding.type_instance_id
                ):
                    cr_stmt = select(CastRule).where(
                        CastRule.source_data_type_id
                        == src_binding.type_instance.data_type_id,
                        CastRule.target_data_type_id
                        == tgt_binding.type_instance.data_type_id,
                    )
                    cr_result = await uow.session.execute(cr_stmt)
                    cast_rule = cr_result.scalars().first()

                inputs = CompatInputs(
                    target_field_origin=tgt_field.origin,
                    source_binding=_binding_to_dict(src_binding),
                    target_binding=_binding_to_dict(tgt_binding),
                    cast_rule=(
                        {"id": cast_rule.id, "safety": cast_rule.safety}
                        if cast_rule is not None
                        else None
                    ),
                )
                issues = compute_field_compat_issues(inputs)
                severity = _severity_of_issues(issues)

                if severity == CompatSeverity.OK:
                    ok_count += 1
                elif severity == CompatSeverity.WARN:
                    warn_count += 1
                else:
                    error_count += 1

                field_compat.append(
                    FieldCompatRow(
                        field_link_id=fl.id,
                        source_field=FieldCompatFieldRef(
                            id=src_field.id, name=src_field.name
                        ),
                        target_field=FieldCompatFieldRef(
                            id=tgt_field.id, name=tgt_field.name
                        ),
                        source_type=_render_type(src_binding),
                        target_type=_render_type(tgt_binding),
                        issues=issues,
                        severity=severity,
                        cast_rule_id=cast_rule.id if cast_rule is not None else None,
                    )
                )

            summary = CompatSummary(
                ok=ok_count,
                warn=warn_count,
                error=error_count,
                total=ok_count + warn_count + error_count,
            )

            has_drift = pin_drift.source.has_drift or pin_drift.target.has_drift
            if error_count > 0:
                status = CompatSeverity.ERROR
            elif warn_count > 0 or has_drift:
                status = CompatSeverity.WARN
            else:
                status = CompatSeverity.OK

            return DatasetLinkCompatReport(
                dataset_link_id=dataset_link_id,
                pin_drift=pin_drift,
                field_compat=field_compat,
                summary=summary,
                status=status,
            )
