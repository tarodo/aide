import textwrap
from pathlib import Path

import pytest
from sqlalchemy import select

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


def test_postgres14_yaml_numeric_has_precision_limits():
    parsed = load_seed_file(POSTGRES14_YAML)
    numeric = next(t for t in parsed.types if t.code == "numeric")
    assert numeric.params_schema["precision"].min == 1
    assert numeric.params_schema["precision"].max == 1000

    ts = next(t for t in parsed.types if t.code == "timestamp")
    assert ts.params_schema["precision"].min == 0
    assert ts.params_schema["precision"].max == 6


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
async def test_main_dry_run_rolls_back(transactional_session, tmp_path):
    """_main rolls back when dry_run=True."""
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)

    report = await seed_main(transactional_session, file=p, dry_run=True)
    assert report.types_inserted == 2

    # After rollback, the rows should be gone.
    rows = (
        (
            await transactional_session.execute(
                select(DataType).where(DataType.code.in_(["bigint", "varchar"]))
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_main_commit_persists(transactional_session, tmp_path):
    """_main commits when dry_run=False; transactional_session outer rollback still cleans up."""
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)

    report = await seed_main(transactional_session, file=p, dry_run=False)
    assert report.types_inserted == 2

    rows = (
        (
            await transactional_session.execute(
                select(DataType).where(DataType.code.in_(["bigint", "varchar"]))
            )
        )
        .scalars()
        .all()
    )
    assert {r.code for r in rows} == {"bigint", "varchar"}
