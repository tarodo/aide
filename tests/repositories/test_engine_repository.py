import uuid

import pytest

from backend.models.engine import EngineDebezium, EngineSpark
from backend.repositories.engine import EngineRepository


@pytest.mark.asyncio
async def test_repo_get_returns_polymorphic_subtype(transactional_session):
    repo = EngineRepository(transactional_session)
    spark = EngineSpark(
        code="spark-r1",
        name="r",
        kind="spark",
        role="compute",
        version="3.x",
    )
    transactional_session.add(spark)
    await transactional_session.flush()

    fetched = await repo.get(spark.id)
    assert isinstance(fetched, EngineSpark)
    assert fetched.code == "spark-r1"


@pytest.mark.asyncio
async def test_repo_get_excludes_soft_deleted(transactional_session):
    from sqlalchemy import func

    repo = EngineRepository(transactional_session)
    dbz = EngineDebezium(
        code="dbz-r1",
        name="r",
        kind="debezium",
        role="cdc",
        version="2.x",
        envelope_template={"envelope_kind": "debezium", "after_path": "after"},
    )
    transactional_session.add(dbz)
    await transactional_session.flush()
    dbz.deleted_at = func.now()
    await transactional_session.flush()

    assert await repo.get(dbz.id) is None
    assert await repo.get_including_deleted(dbz.id) is not None


@pytest.mark.asyncio
async def test_repo_get_by_code_active(transactional_session):
    repo = EngineRepository(transactional_session)
    eng = EngineSpark(
        code="spark-by-code",
        name="r",
        kind="spark",
        role="compute",
        version="3.x",
    )
    transactional_session.add(eng)
    await transactional_session.flush()

    found = await repo.get_by_code(eng.code)
    assert found is not None
    assert found.id == eng.id

    missing = await repo.get_by_code("nope-" + uuid.uuid4().hex)
    assert missing is None


@pytest.mark.asyncio
async def test_repo_paginated_filters_by_role(transactional_session):
    repo = EngineRepository(transactional_session)
    transactional_session.add_all(
        [
            EngineSpark(
                code="s1", name="a", kind="spark", role="compute", version="3.x"
            ),
            EngineDebezium(
                code="d1",
                name="b",
                kind="debezium",
                role="cdc",
                version="2.x",
                envelope_template={"envelope_kind": "debezium", "after_path": "after"},
            ),
        ]
    )
    await transactional_session.flush()

    items, total = await repo.get_multi_paginated(
        skip=0, limit=10, filters={"role": "compute"}
    )
    assert total == 1
    assert items[0].code == "s1"
