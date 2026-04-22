import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)


@pytest.mark.asyncio
async def test_template_create(transactional_session: AsyncSession):
    tpl = TechFieldTemplate(
        code="scd2_core_v1",
        name="SCD2 on CORE",
        layer="core",
    )
    transactional_session.add(tpl)
    await transactional_session.flush()
    await transactional_session.refresh(tpl)
    assert tpl.id is not None
    assert tpl.row_version == 1


@pytest.mark.asyncio
async def test_template_code_unique(transactional_session: AsyncSession):
    transactional_session.add(
        TechFieldTemplate(code="dup_code", name="A", layer="core")
    )
    await transactional_session.flush()
    transactional_session.add(TechFieldTemplate(code="dup_code", name="B", layer="raw"))
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_template_field_create(transactional_session: AsyncSession):
    tpl = TechFieldTemplate(code="fld_t1", name="T1", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()
    tf = TechFieldTemplateField(
        template_id=tpl.id,
        name="valid_from",
        type_code="TIMESTAMP",
        order=0,
    )
    transactional_session.add(tf)
    await transactional_session.flush()
    await transactional_session.refresh(tf)
    assert tf.id is not None


@pytest.mark.asyncio
async def test_template_field_name_unique_per_template(
    transactional_session: AsyncSession,
):
    tpl = TechFieldTemplate(code="fld_t2", name="T2", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()
    transactional_session.add(
        TechFieldTemplateField(
            template_id=tpl.id, name="same", type_code="STRING", order=0
        )
    )
    await transactional_session.flush()
    transactional_session.add(
        TechFieldTemplateField(
            template_id=tpl.id, name="same", type_code="BIGINT", order=1
        )
    )
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_template_field_cascade_on_template_delete(
    transactional_session: AsyncSession,
):
    tpl = TechFieldTemplate(code="fld_c1", name="C1", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()
    transactional_session.add(
        TechFieldTemplateField(
            template_id=tpl.id, name="a", type_code="STRING", order=0
        )
    )
    await transactional_session.flush()

    await transactional_session.delete(tpl)
    await transactional_session.flush()
    remaining = (
        (await transactional_session.execute(select(TechFieldTemplateField)))
        .scalars()
        .all()
    )
    assert len(remaining) == 0
