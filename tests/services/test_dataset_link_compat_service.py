import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aide_schemas.cast_rule import CastSafety
from aide_schemas.lineage_compat import FieldCompatIssue
from backend.db.uow import UnitOfWork
from backend.models import System, SystemFlavor, SystemKind
from backend.models.data_type import DataType
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.models.field import Field
from backend.models.field_binding import FieldBinding
from backend.models.field_link import FieldLink
from backend.models.type_instance import TypeInstance
from backend.services.dataset_link_compat import (
    CompatInputs,
    DatasetLinkCompatService,
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


@pytest.mark.asyncio
async def test_compat_report_reports_ok_for_exact_type_match(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="CPT_K", name="CPT Kind")
    flavor = SystemFlavor(code="CPT_F", name="CPT Flavor", kind=kind)
    system = System(code="CPT_S", name="CPT System", flavor=flavor)
    src = DatasetRdbms(
        system=system,
        object_name="cpt_src",
        kind="rdbms",
        layer="source",
        schema_name="s",
        table_name="src",
    )
    tgt = DatasetRdbms(
        system=system,
        object_name="cpt_tgt",
        kind="rdbms",
        layer="raw",
        schema_name="s",
        table_name="tgt",
    )
    dt = DataType(code="integer", system_flavor=flavor, params_schema={})
    ti = TypeInstance(data_type=dt, type_params={})

    src_field = Field(dataset=src, name="id", origin="mapped")
    tgt_field = Field(dataset=tgt, name="id", origin="mapped")
    src_schema = DatasetSchema(dataset=src, version_num=1, schema={})
    tgt_schema = DatasetSchema(dataset=tgt, version_num=1, schema={})
    transactional_session.add_all(
        [
            kind,
            flavor,
            system,
            src,
            tgt,
            dt,
            ti,
            src_field,
            tgt_field,
            src_schema,
            tgt_schema,
        ]
    )
    await transactional_session.flush()

    src_binding = FieldBinding(
        field=src_field,
        dataset_schema=src_schema,
        position=0,
        is_nullable=False,
        type_instance=ti,
    )
    tgt_binding = FieldBinding(
        field=tgt_field,
        dataset_schema=tgt_schema,
        position=0,
        is_nullable=False,
        type_instance=ti,
    )
    link = DatasetLink(
        source_dataset_id=src.id,
        target_dataset_id=tgt.id,
        source_schema_id=src_schema.id,
        target_schema_id=tgt_schema.id,
    )
    transactional_session.add_all([src_binding, tgt_binding, link])
    await transactional_session.flush()

    field_link = FieldLink(
        dataset_link_id=link.id,
        source_field_id=src_field.id,
        target_field_id=tgt_field.id,
    )
    transactional_session.add(field_link)
    await transactional_session.flush()

    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session
    async with uow:
        svc = DatasetLinkCompatService()
        report = await svc.compat_report(uow, link.id)

    assert report.status.value == "ok"
    assert report.summary.ok == 1
    assert report.summary.error == 0
    assert report.summary.warn == 0
    assert report.pin_drift.source.has_drift is False
    assert report.pin_drift.target.has_drift is False
