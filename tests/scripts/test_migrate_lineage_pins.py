import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.scripts.migrate_lineage_pins import (
    _latest_schema,
    backfill_dataset_link_pins,
    backfill_field_origin,
)


@pytest.mark.asyncio
async def test_backfill_pins_is_noop_when_all_links_already_pinned(
    transactional_session: AsyncSession,
):
    """Post-Migration-B state: every DatasetLink has NOT NULL pins, so the
    WHERE-NULL filter matches nothing. Function returns empty unresolved list."""
    unresolved = await backfill_dataset_link_pins(transactional_session)
    assert unresolved == []


@pytest.mark.asyncio
async def test_backfill_field_origin_runs_cleanly_when_nothing_to_backfill(
    transactional_session: AsyncSession,
):
    """At this stage the test DB has Migration A applied (is_tech still
    present) but no rows with is_tech=True. The UPDATE runs with 0 rows
    affected and the function returns True. The post-Migration-B rollback
    branch is not exercised here — that requires running with is_tech
    physically dropped, which only happens after Task 8."""
    result = await backfill_field_origin(transactional_session)
    assert result is True


@pytest.mark.asyncio
async def test_latest_schema_returns_highest_version(
    transactional_session: AsyncSession,
):
    """Spot-check the helper."""
    from backend.models import System, SystemFlavor, SystemKind
    from backend.models.dataset import DatasetRdbms
    from backend.models.dataset_schema import DatasetSchema

    kind = SystemKind(code="BF_LS_K", name="BF LS Kind")
    flavor = SystemFlavor(code="BF_LS_F", name="BF LS Flavor", kind=kind)
    system = System(code="BF_LS_S", name="BF LS System", flavor=flavor)
    ds = DatasetRdbms(
        system=system,
        object_name="bf_ls_ds",
        kind="rdbms",
        schema_name="s",
        table_name="t",
    )
    transactional_session.add_all([kind, flavor, system, ds])
    await transactional_session.flush()
    transactional_session.add_all(
        [
            DatasetSchema(dataset_id=ds.id, version_num=1, schema={}),
            DatasetSchema(dataset_id=ds.id, version_num=5, schema={}),
        ]
    )
    await transactional_session.flush()

    latest = await _latest_schema(transactional_session, ds.id)
    assert latest is not None
    assert latest.version_num == 5
