import textwrap
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from backend.core.settings import settings
from backend.models.data_type import DataType
from backend.models.system_flavor import SystemFlavor
from backend.models.system_kind import SystemKind
from backend.scripts._seed_core import load_seed_file, seed_from_file
from backend.scripts.seed_data_types import _main as seed_main

POSTGRES14_YAML = Path("backend/scripts/data/postgres14.yaml")

EXPECTED_PG14_TYPE_CODES = {
    "smallint",
    "integer",
    "bigint",
    "decimal",
    "numeric",
    "real",
    "double",
    "smallserial",
    "serial",
    "bigserial",
    "money",
    "char",
    "varchar",
    "text",
    "bytea",
    "date",
    "time",
    "timetz",
    "timestamp",
    "timestamptz",
    "interval",
    "boolean",
    "enum",
    "point",
    "line",
    "lseg",
    "box",
    "path",
    "polygon",
    "circle",
    "inet",
    "cidr",
    "macaddr",
    "macaddr8",
    "bit",
    "varbit",
    "tsvector",
    "tsquery",
    "uuid",
    "xml",
    "json",
    "jsonb",
    "array",
    "int4range",
    "int8range",
    "numrange",
    "tsrange",
    "tstzrange",
    "daterange",
    "oid",
    "pg_lsn",
    "txid_snapshot",
}


def test_postgres14_yaml_loads_and_covers_all_expected_codes():
    parsed = load_seed_file(POSTGRES14_YAML)
    assert parsed.flavor.code == "postgres14"
    codes = {t.code for t in parsed.types}
    missing = EXPECTED_PG14_TYPE_CODES - codes
    extra = codes - EXPECTED_PG14_TYPE_CODES
    assert not missing, f"Missing types: {sorted(missing)}"
    assert not extra, f"Unexpected types: {sorted(extra)}"


@pytest.mark.asyncio
async def test_seed_from_real_postgres14_yaml(transactional_session):
    report = await seed_from_file(transactional_session, POSTGRES14_YAML)
    assert report.kind in {"inserted", "unchanged", "updated", "restored"}
    assert report.types_inserted == len(EXPECTED_PG14_TYPE_CODES)


SAMPLE_YAML = textwrap.dedent("""
    kind: {code: rdbms, name: Relational Database}
    flavor:
      code: postgres14
      name: PostgreSQL
      vendor: PGDG
      versions: ["14", "15"]
    types:
      - code: bigint
        params_schema: {}
        render_template: bigint
      - code: varchar
        params_schema:
          length: {type: int, required: false, default: null}
        render_template: "varchar({length})"
    """)


@pytest.mark.asyncio
async def test_seed_from_file_inserts_everything(transactional_session, tmp_path):
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)

    report = await seed_from_file(transactional_session, p)

    assert report.kind == "inserted"
    assert report.flavor == "inserted"
    assert report.types_inserted == 2
    assert report.types_updated == 0
    assert report.types_unchanged == 0

    kinds = (await transactional_session.execute(select(SystemKind))).scalars().all()
    assert len(kinds) == 1
    flavors = (
        (await transactional_session.execute(select(SystemFlavor))).scalars().all()
    )
    assert len(flavors) == 1
    types = (await transactional_session.execute(select(DataType))).scalars().all()
    assert {t.code for t in types} == {"bigint", "varchar"}


@pytest.mark.asyncio
async def test_seed_from_file_is_idempotent(transactional_session, tmp_path):
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)

    await seed_from_file(transactional_session, p)
    report = await seed_from_file(transactional_session, p)

    assert report.kind == "unchanged"
    assert report.flavor == "unchanged"
    assert report.types_inserted == 0
    assert report.types_unchanged == 2


@pytest.mark.asyncio
async def test_seed_from_file_updates_changed_template(transactional_session, tmp_path):
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)
    await seed_from_file(transactional_session, p)

    modified = SAMPLE_YAML.replace("render_template: bigint", "render_template: int8")
    p.write_text(modified)

    report = await seed_from_file(transactional_session, p)
    assert report.types_updated == 1
    assert report.types_unchanged == 1


@pytest.mark.asyncio
async def test_cli_dry_run_rolls_back(tmp_path):
    """Dry run: seed runs inside its own session and rolls back."""
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)

    engine = create_async_engine(settings.DATABASE_URL)
    try:
        report = await seed_main(
            file=p,
            dry_run=True,
            session_factory=lambda: AsyncSession(engine, expire_on_commit=False),
        )
        assert report.types_inserted == 2

        # Verify nothing persisted.
        async with AsyncSession(engine, expire_on_commit=False) as session:
            rows = (await session.execute(select(DataType))).scalars().all()
            assert all(r.code not in {"bigint", "varchar"} for r in rows)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cli_commit_persists(tmp_path):
    """Real commit path persists. Test cleans up after itself."""
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)

    engine = create_async_engine(settings.DATABASE_URL)
    try:
        report = await seed_main(
            file=p,
            dry_run=False,
            session_factory=lambda: AsyncSession(engine, expire_on_commit=False),
        )
        assert report.types_inserted == 2

        async with AsyncSession(engine, expire_on_commit=False) as session:
            rows = (await session.execute(select(DataType))).scalars().all()
            assert {"bigint", "varchar"}.issubset({r.code for r in rows})
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                delete(DataType).where(DataType.code.in_(["bigint", "varchar"]))
            )
            await session.execute(
                delete(SystemFlavor).where(SystemFlavor.code == "postgres14")
            )
            await session.execute(delete(SystemKind).where(SystemKind.code == "rdbms"))
            await session.commit()
        await engine.dispose()
