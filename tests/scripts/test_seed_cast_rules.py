from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from backend.models.cast_rule import CastRule
from backend.scripts._seed_cast_rules_core import (
    CastRulesSeedFile,
    load_seed_file,
    seed_from_file,
)
from backend.scripts._seed_core import seed_from_file as seed_data_types_from_file


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "casts.yaml"
    p.write_text(content)
    return p


@pytest.mark.asyncio
async def test_load_seed_file_parses_minimal(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
mappings:
  - source: {flavor: postgres14, code: bigint}
    target: {flavor: iceberg_v2, code: long}
    safety: implicit
    params: {}
""",
    )
    sf = load_seed_file(p)
    assert isinstance(sf, CastRulesSeedFile)
    assert len(sf.mappings) == 1
    assert sf.mappings[0].safety == "implicit"


@pytest.mark.asyncio
async def test_load_seed_file_rejects_unknown_safety(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
mappings:
  - source: {flavor: postgres14, code: bigint}
    target: {flavor: iceberg_v2, code: long}
    safety: maybe
    params: {}
""",
    )
    with pytest.raises(ValueError):
        load_seed_file(p)


@pytest.mark.asyncio
async def test_seed_from_file_inserts_and_is_idempotent(
    transactional_session, tmp_path: Path
) -> None:
    # Seed both flavors via the existing data-type seeder.
    pg14 = _write(
        tmp_path,
        """
kind: {code: rdbms, name: Relational Database}
flavor:
  code: postgres14
  name: PostgreSQL
  vendor: PG
  versions: ["14"]
types:
  - {code: bigint, params_schema: {}, render_template: bigint}
""",
    )
    iceberg = tmp_path / "iceberg.yaml"
    iceberg.write_text("""
kind: {code: hive, name: Hive Metastore Lake}
flavor:
  code: iceberg_v2
  name: Apache Iceberg
  vendor: ASF
  versions: ["2"]
types:
  - {code: long, params_schema: {}, render_template: long}
""")
    await seed_data_types_from_file(transactional_session, pg14)
    await seed_data_types_from_file(transactional_session, iceberg)

    casts = _write(
        tmp_path,
        """
mappings:
  - source: {flavor: postgres14, code: bigint}
    target: {flavor: iceberg_v2, code: long}
    safety: implicit
    params: {}
""",
    )

    report1 = await seed_from_file(transactional_session, casts)
    assert report1.inserted == 1
    assert report1.unchanged == 0

    report2 = await seed_from_file(transactional_session, casts)
    assert report2.inserted == 0
    assert report2.unchanged == 1

    rows = (await transactional_session.execute(select(CastRule))).scalars().all()
    assert len(rows) == 1
    assert rows[0].safety == "implicit"


@pytest.mark.asyncio
async def test_seed_from_file_updates_safety_change(
    transactional_session, tmp_path: Path
) -> None:
    # Pre-seed types.
    seed_pg = tmp_path / "pg.yaml"
    seed_pg.write_text("""
kind: {code: rdbms, name: Relational Database}
flavor: {code: postgres14, name: PostgreSQL, versions: ["14"]}
types:
  - {code: bigint, params_schema: {}, render_template: bigint}
""")
    seed_ice = tmp_path / "ice.yaml"
    seed_ice.write_text("""
kind: {code: hive, name: Hive Metastore Lake}
flavor: {code: iceberg_v2, name: Apache Iceberg, versions: ["2"]}
types:
  - {code: long, params_schema: {}, render_template: long}
""")
    await seed_data_types_from_file(transactional_session, seed_pg)
    await seed_data_types_from_file(transactional_session, seed_ice)

    casts1 = tmp_path / "c1.yaml"
    casts1.write_text("""
mappings:
  - source: {flavor: postgres14, code: bigint}
    target: {flavor: iceberg_v2, code: long}
    safety: safe
    params: {}
""")
    await seed_from_file(transactional_session, casts1)

    casts2 = tmp_path / "c2.yaml"
    casts2.write_text("""
mappings:
  - source: {flavor: postgres14, code: bigint}
    target: {flavor: iceberg_v2, code: long}
    safety: implicit
    params: {}
""")
    report = await seed_from_file(transactional_session, casts2)
    assert report.updated == 1

    row = (await transactional_session.execute(select(CastRule))).scalars().first()
    assert row.safety == "implicit"


@pytest.mark.asyncio
async def test_seed_from_file_fails_on_missing_data_type(
    transactional_session, tmp_path: Path
) -> None:
    # Seed only the source flavor.
    seed_pg = tmp_path / "pg.yaml"
    seed_pg.write_text("""
kind: {code: rdbms, name: Relational Database}
flavor: {code: postgres14, name: PostgreSQL, versions: ["14"]}
types:
  - {code: bigint, params_schema: {}, render_template: bigint}
""")
    await seed_data_types_from_file(transactional_session, seed_pg)

    casts = tmp_path / "c.yaml"
    casts.write_text("""
mappings:
  - source: {flavor: postgres14, code: bigint}
    target: {flavor: iceberg_v2, code: long}
    safety: implicit
    params: {}
""")
    with pytest.raises(LookupError):
        await seed_from_file(transactional_session, casts)
