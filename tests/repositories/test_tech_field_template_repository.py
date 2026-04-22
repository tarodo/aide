import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)
from backend.repositories.tech_field_template import TechFieldTemplateRepository
from backend.repositories.tech_field_template_field import (
    TechFieldTemplateFieldRepository,
)


@pytest.mark.asyncio
async def test_get_by_code(transactional_session: AsyncSession):
    tpl = TechFieldTemplate(code="repo_gc", name="RepoGC", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()

    repo = TechFieldTemplateRepository(transactional_session)
    found = await repo.get_by_code("repo_gc")
    assert found is not None and found.id == tpl.id
    assert await repo.get_by_code("nope") is None


@pytest.mark.asyncio
async def test_list_by_template(transactional_session: AsyncSession):
    tpl = TechFieldTemplate(code="repo_lt", name="RepoLT", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()
    transactional_session.add_all(
        [
            TechFieldTemplateField(
                template_id=tpl.id, name="a", type_code="STRING", order=1
            ),
            TechFieldTemplateField(
                template_id=tpl.id, name="b", type_code="STRING", order=0
            ),
        ]
    )
    await transactional_session.flush()

    repo = TechFieldTemplateFieldRepository(transactional_session)
    items = await repo.list_by_template(tpl.id)
    assert [it.name for it in items] == ["b", "a"]


@pytest.mark.asyncio
async def test_get_by_template_and_name(transactional_session: AsyncSession):
    tpl = TechFieldTemplate(code="repo_gtn", name="RepoGTN", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()
    tf = TechFieldTemplateField(
        template_id=tpl.id, name="uniq", type_code="BIGINT", order=0
    )
    transactional_session.add(tf)
    await transactional_session.flush()

    repo = TechFieldTemplateFieldRepository(transactional_session)
    found = await repo.get_by_template_and_name(tpl.id, "uniq")
    assert found is not None and found.id == tf.id
    assert await repo.get_by_template_and_name(tpl.id, "missing") is None
