import pytest
from sqlalchemy import select
from sqlalchemy.orm import with_polymorphic

from backend.models.engine import (
    Engine,
    EngineDebezium,
    EngineOgg,
    EngineSpark,
)


@pytest.mark.asyncio
async def test_engine_polymorphic_roundtrip(transactional_session):
    debezium = EngineDebezium(
        code="dbz-1",
        name="Debezium 2.x prod",
        kind="debezium",
        role="cdc",
        version="2.x",
        envelope_template={
            "envelope_kind": "debezium",
            "after_path": "after",
            "before_path": "before",
            "op_path": "op",
            "ts_ms_path": "ts_ms",
            "source_path": "source",
        },
    )
    spark = EngineSpark(
        code="spark-1",
        name="Spark 3.5 cluster",
        kind="spark",
        role="compute",
        version="3.x",
        runtime_opts={"output_mode": "append"},
    )
    transactional_session.add_all([debezium, spark])
    await transactional_session.flush()

    poly = with_polymorphic(Engine, "*")
    result = await transactional_session.execute(select(poly).order_by(poly.code))
    rows = list(result.scalars().all())

    assert len(rows) == 2
    assert {type(r).__name__ for r in rows} == {"EngineDebezium", "EngineSpark"}
    debezium_row = next(r for r in rows if r.code == "dbz-1")
    assert isinstance(debezium_row, EngineDebezium)
    assert debezium_row.envelope_template["after_path"] == "after"


@pytest.mark.asyncio
async def test_engine_ogg_subtype(transactional_session):
    ogg = EngineOgg(
        code="ogg-1",
        name="OGG 21c",
        kind="ogg",
        role="cdc",
        version="21c",
        envelope_template={"envelope_kind": "ogg", "after_path": "after"},
    )
    transactional_session.add(ogg)
    await transactional_session.flush()
    assert ogg.id is not None
    assert ogg.envelope_template["envelope_kind"] == "ogg"
