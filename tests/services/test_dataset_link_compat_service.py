import uuid

from aide_schemas.cast_rule import CastSafety
from aide_schemas.lineage_compat import FieldCompatIssue
from backend.services.dataset_link_compat import (
    CompatInputs,
    compute_field_compat_issues,
)


def _ti(data_type_id: uuid.UUID, params: dict | None = None) -> dict:
    return {
        "id": uuid.uuid4(),
        "data_type_id": data_type_id,
        "type_params": params or {},
    }


def _binding(type_instance: dict, is_nullable: bool = False) -> dict:
    return {
        "id": uuid.uuid4(),
        "type_instance": type_instance,
        "type_instance_id": type_instance["id"],
        "is_nullable": is_nullable,
    }


def test_source_unbound_short_circuits():
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=None,
            target_binding=_binding(_ti(uuid.uuid4())),
            cast_rule=None,
        )
    )
    assert issues == [FieldCompatIssue.SOURCE_UNBOUND]


def test_target_unbound_short_circuits():
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(uuid.uuid4())),
            target_binding=None,
            cast_rule=None,
        )
    )
    assert issues == [FieldCompatIssue.TARGET_UNBOUND]


def test_exact_type_match_no_issues():
    ti = _ti(uuid.uuid4())
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(ti),
            target_binding=_binding(ti),
            cast_rule=None,
        )
    )
    assert issues == []


def test_different_types_no_cast_rule_is_incompatible():
    src_dt_id = uuid.uuid4()
    tgt_dt_id = uuid.uuid4()
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(src_dt_id)),
            target_binding=_binding(_ti(tgt_dt_id)),
            cast_rule=None,
        )
    )
    assert issues == [FieldCompatIssue.TYPE_INCOMPATIBLE]


def test_cast_rule_implicit_is_ok():
    src_dt_id = uuid.uuid4()
    tgt_dt_id = uuid.uuid4()
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(src_dt_id)),
            target_binding=_binding(_ti(tgt_dt_id)),
            cast_rule={"id": uuid.uuid4(), "safety": CastSafety.IMPLICIT.value},
        )
    )
    assert issues == []


def test_cast_rule_safe_is_needs_cast():
    src_dt_id = uuid.uuid4()
    tgt_dt_id = uuid.uuid4()
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(src_dt_id)),
            target_binding=_binding(_ti(tgt_dt_id)),
            cast_rule={"id": uuid.uuid4(), "safety": CastSafety.SAFE.value},
        )
    )
    assert issues == [FieldCompatIssue.TYPE_NEEDS_CAST]


def test_cast_rule_unsafe_is_unsafe_cast():
    src_dt_id = uuid.uuid4()
    tgt_dt_id = uuid.uuid4()
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(src_dt_id)),
            target_binding=_binding(_ti(tgt_dt_id)),
            cast_rule={"id": uuid.uuid4(), "safety": CastSafety.UNSAFE.value},
        )
    )
    assert issues == [FieldCompatIssue.TYPE_UNSAFE_CAST]


def test_nullability_tightening_warns():
    ti = _ti(uuid.uuid4())
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(ti, is_nullable=True),
            target_binding=_binding(ti, is_nullable=False),
            cast_rule=None,
        )
    )
    assert issues == [FieldCompatIssue.NULLABILITY_WARN]


def test_type_needs_cast_plus_nullability_warn_combined():
    src_dt_id = uuid.uuid4()
    tgt_dt_id = uuid.uuid4()
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(src_dt_id), is_nullable=True),
            target_binding=_binding(_ti(tgt_dt_id), is_nullable=False),
            cast_rule={"id": uuid.uuid4(), "safety": CastSafety.SAFE.value},
        )
    )
    assert set(issues) == {
        FieldCompatIssue.TYPE_NEEDS_CAST,
        FieldCompatIssue.NULLABILITY_WARN,
    }


def test_target_not_mapped_returns_empty_defensive():
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="deprecated",
            source_binding=_binding(_ti(uuid.uuid4())),
            target_binding=_binding(_ti(uuid.uuid4())),
            cast_rule=None,
        )
    )
    assert issues == []
