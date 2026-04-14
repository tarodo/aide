import pytest
from sqlalchemy import select

from backend.models.system_kind import SystemKind
from backend.scripts._seed_core import (
    SeedFlavor,
    SeedKind,
    SeedParamSpec,
    SeedType,
    upsert_data_type,
    upsert_system_flavor,
    upsert_system_kind,
)


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
    from datetime import datetime, timezone

    obj, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    obj.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
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


@pytest.mark.asyncio
async def test_upsert_flavor_inserts_with_kind_fk(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    spec = SeedFlavor(
        code="postgres14",
        name="PostgreSQL",
        vendor="PGDG",
        versions=["14", "15"],
    )
    obj, status = await upsert_system_flavor(transactional_session, spec, kind.id)
    assert status == "inserted"
    assert obj.kind_id == kind.id
    assert obj.versions == ["14", "15"]


@pytest.mark.asyncio
async def test_upsert_flavor_updates_when_versions_change(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    await upsert_system_flavor(
        transactional_session,
        SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14"]),
        kind.id,
    )
    obj, status = await upsert_system_flavor(
        transactional_session,
        SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14", "15"]),
        kind.id,
    )
    assert status == "updated"
    assert obj.versions == ["14", "15"]


@pytest.mark.asyncio
async def test_upsert_flavor_noop_when_unchanged(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    spec = SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14"])
    await upsert_system_flavor(transactional_session, spec, kind.id)
    _, status = await upsert_system_flavor(transactional_session, spec, kind.id)
    assert status == "unchanged"


@pytest.mark.asyncio
async def test_upsert_data_type_inserts_when_missing(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    flavor, _ = await upsert_system_flavor(
        transactional_session,
        SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14"]),
        kind.id,
    )
    spec = SeedType(
        code="varchar",
        params_schema={
            "length": SeedParamSpec(type="int", required=False, default=None)
        },
        render_template="varchar({length})",
    )
    obj, status = await upsert_data_type(transactional_session, spec, flavor.id)
    assert status == "inserted"
    assert obj.code == "varchar"
    assert obj.params_schema == {
        "length": {
            "type": "int",
            "required": False,
            "default": None,
            "min": None,
            "max": None,
        }
    }


@pytest.mark.asyncio
async def test_upsert_data_type_updates_when_template_changes(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    flavor, _ = await upsert_system_flavor(
        transactional_session,
        SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14"]),
        kind.id,
    )
    await upsert_data_type(
        transactional_session,
        SeedType(code="bigint", params_schema={}, render_template="bigint"),
        flavor.id,
    )
    _, status = await upsert_data_type(
        transactional_session,
        SeedType(code="bigint", params_schema={}, render_template="int8"),
        flavor.id,
    )
    assert status == "updated"


@pytest.mark.asyncio
async def test_upsert_data_type_noop_when_unchanged(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    flavor, _ = await upsert_system_flavor(
        transactional_session,
        SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14"]),
        kind.id,
    )
    spec = SeedType(code="bigint", params_schema={}, render_template="bigint")
    await upsert_data_type(transactional_session, spec, flavor.id)
    _, status = await upsert_data_type(transactional_session, spec, flavor.id)
    assert status == "unchanged"
