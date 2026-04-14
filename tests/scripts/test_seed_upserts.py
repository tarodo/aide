import pytest
from sqlalchemy import select

from backend.models.system_kind import SystemKind
from backend.scripts._seed_core import SeedKind, upsert_system_kind


@pytest.mark.asyncio
async def test_upsert_kind_inserts_when_missing(transactional_session):
    spec = SeedKind(code="rdbms", name="Relational Database")
    obj, status = await upsert_system_kind(transactional_session, spec)
    assert status == "inserted"
    assert obj.code == "rdbms"
    assert obj.name == "Relational Database"


@pytest.mark.asyncio
async def test_upsert_kind_noop_when_unchanged(transactional_session):
    spec = SeedKind(code="rdbms", name="Relational Database")
    await upsert_system_kind(transactional_session, spec)
    _, status = await upsert_system_kind(transactional_session, spec)
    assert status == "unchanged"


@pytest.mark.asyncio
async def test_upsert_kind_updates_when_name_changes(transactional_session):
    await upsert_system_kind(transactional_session, SeedKind(code="rdbms", name="Old"))
    obj, status = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="New")
    )
    assert status == "updated"
    assert obj.name == "New"


@pytest.mark.asyncio
async def test_upsert_kind_restores_soft_deleted(transactional_session):
    from datetime import datetime

    obj, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    obj.deleted_at = datetime.utcnow()
    await transactional_session.flush()

    obj2, status = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    assert status == "restored"
    assert obj2.deleted_at is None

    check = await transactional_session.execute(
        select(SystemKind).where(SystemKind.code == "rdbms")
    )
    assert len(check.scalars().all()) == 1
