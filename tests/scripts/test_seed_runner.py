import textwrap

import pytest
from sqlalchemy import select

from backend.models.data_type import DataType
from backend.models.system_flavor import SystemFlavor
from backend.models.system_kind import SystemKind
from backend.scripts._seed_core import seed_from_file

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
