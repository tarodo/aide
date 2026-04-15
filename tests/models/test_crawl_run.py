from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import CrawlRun, System, SystemFlavor, SystemKind


@pytest_asyncio.fixture
async def seed_system(transactional_session: AsyncSession) -> System:
    kind = SystemKind(code="RDBMS_CR_MODEL_TEST", name="RDBMS for CrawlRun Model Test")
    flavor = SystemFlavor(
        code="PG_CR_MODEL_TEST",
        name="Postgres for CrawlRun Model Test",
        kind=kind,
    )
    system = System(
        code="pg-cr-model-test", name="PG CrawlRun Model Test", flavor=flavor
    )
    transactional_session.add_all([kind, flavor, system])
    await transactional_session.commit()
    await transactional_session.refresh(system)
    return system


@pytest.mark.asyncio
async def test_diff_payload_roundtrip(
    transactional_session: AsyncSession, seed_system: System
):
    run = CrawlRun(
        system_id=seed_system.id,
        status="completed",
        started_at=datetime.now(timezone.utc),
        config={},
        diff_payload={
            "schema_version": 1,
            "new_datasets_applied": [],
            "existing_datasets_diff": [],
            "removed_datasets": [],
        },
    )
    transactional_session.add(run)
    await transactional_session.commit()
    await transactional_session.refresh(run)
    assert run.diff_payload["schema_version"] == 1
