from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.tech_field_template import TechFieldTemplate
from backend.scripts.seed_tech_templates import seed_from_file

SAMPLE_YAML = """
templates:
  - code: scd2_core_v1
    name: SCD2 on CORE
    layer: core
    fields:
      - name: valid_from
        type_code: TIMESTAMP
        order: 0
      - name: valid_to
        type_code: TIMESTAMP
        order: 1
"""


@pytest.mark.asyncio
async def test_seed_inserts(transactional_session: AsyncSession, tmp_path: Path):
    path = tmp_path / "t.yaml"
    path.write_text(SAMPLE_YAML)
    report = await seed_from_file(transactional_session, path)
    assert report.templates_inserted == 1
    assert report.fields_inserted == 2

    row = (
        (
            await transactional_session.execute(
                select(TechFieldTemplate).options(
                    selectinload(TechFieldTemplate.fields)
                )
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert row.code == "scd2_core_v1"
    assert len(row.fields) == 2


@pytest.mark.asyncio
async def test_seed_idempotent(transactional_session: AsyncSession, tmp_path: Path):
    path = tmp_path / "t.yaml"
    path.write_text(SAMPLE_YAML)
    first = await seed_from_file(transactional_session, path)
    second = await seed_from_file(transactional_session, path)
    assert first.templates_inserted == 1 and first.fields_inserted == 2
    assert second.templates_inserted == 0 and second.fields_inserted == 0
    assert second.templates_unchanged == 1
