import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.dataset import DatasetHive, DatasetKafka
from backend.models.dataset_link import DatasetLink
from backend.models.engine import EngineDebezium, EngineImpala, EngineSpark
from backend.models.field import Field
from backend.models.field_link import FieldLink
from backend.services.engine_render_service import EngineRenderService


def _mk_uow() -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.session = MagicMock()
    uow.dataset_links = MagicMock()
    uow.engines = MagicMock()
    uow.datasets = MagicMock()
    uow.field_links = MagicMock()
    uow.fields = MagicMock()
    return uow


def _spark() -> EngineSpark:
    e = EngineSpark(code="s", name="s", kind="spark", role="compute", version="3.x")
    e.id = uuid.uuid4()
    return e


def _impala() -> EngineImpala:
    e = EngineImpala(code="i", name="i", kind="impala", role="compute", version="4.x")
    e.id = uuid.uuid4()
    return e


def _debezium() -> EngineDebezium:
    e = EngineDebezium(
        code="d",
        name="d",
        kind="debezium",
        role="cdc",
        version="2.x",
        envelope_template={"envelope_kind": "debezium", "after_path": "after"},
    )
    e.id = uuid.uuid4()
    return e


def _hive_dataset() -> DatasetHive:
    d = DatasetHive(
        system_id=uuid.uuid4(),
        object_name="t",
        kind="hive",
        catalog_uri="thrift://hms",
        db_name="raw",
        table_name="t",
        file_format="parquet",
    )
    d.id = uuid.uuid4()
    return d


def _kafka_dataset(fmt: str = "json") -> DatasetKafka:
    d = DatasetKafka(
        system_id=uuid.uuid4(),
        object_name="topic",
        kind="kafka",
        topic="topic",
        format=fmt,
        partitions=1,
        retention_ms=86400000,
        key_columns=["id"],
    )
    d.id = uuid.uuid4()
    return d


def _link(
    source_id: uuid.UUID, target_id: uuid.UUID, engine_id: uuid.UUID | None = None
) -> DatasetLink:
    link = DatasetLink(
        source_dataset_id=source_id,
        target_dataset_id=target_id,
        source_schema_id=uuid.uuid4(),
        target_schema_id=uuid.uuid4(),
    )
    link.id = uuid.uuid4()
    link.engine_id = engine_id
    link.deleted_at = None
    return link


def _field(name: str, dataset_id: uuid.UUID, type_code: str | None = None) -> Field:
    f = Field(dataset_id=dataset_id, name=name, origin="mapped")
    f.id = uuid.uuid4()
    if type_code is not None:
        f.extra = {"data_type_code": type_code}
    return f


def _field_link(link_id: uuid.UUID, src_id: uuid.UUID, tgt_id: uuid.UUID) -> FieldLink:
    fl = FieldLink(
        dataset_link_id=link_id, source_field_id=src_id, target_field_id=tgt_id
    )
    fl.id = uuid.uuid4()
    return fl


@pytest.mark.asyncio
async def test_render_no_link_raises_not_found():
    service = EngineRenderService()
    uow = _mk_uow()
    uow.dataset_links.get = AsyncMock(return_value=None)

    with pytest.raises(AppException) as exc:
        await service.render_sql(uow=uow, dataset_link_id=uuid.uuid4())
    assert exc.value.error_code == errors.DATASET_LINK_NOT_FOUND


@pytest.mark.asyncio
async def test_render_no_engine_attached():
    service = EngineRenderService()
    uow = _mk_uow()
    link = _link(uuid.uuid4(), uuid.uuid4(), engine_id=None)
    uow.dataset_links.get = AsyncMock(return_value=link)

    with pytest.raises(AppException) as exc:
        await service.render_sql(uow=uow, dataset_link_id=link.id)
    assert exc.value.error_code == errors.ENGINE_NOT_ATTACHED


@pytest.mark.asyncio
async def test_render_engine_missing():
    service = EngineRenderService()
    uow = _mk_uow()
    eid = uuid.uuid4()
    link = _link(uuid.uuid4(), uuid.uuid4(), engine_id=eid)
    uow.dataset_links.get = AsyncMock(return_value=link)
    uow.engines.get = AsyncMock(return_value=None)

    with pytest.raises(AppException) as exc:
        await service.render_sql(uow=uow, dataset_link_id=link.id)
    assert exc.value.error_code == errors.ENGINE_NOT_FOUND


@pytest.mark.asyncio
async def test_render_cdc_engine_rejected():
    service = EngineRenderService()
    uow = _mk_uow()
    debezium = _debezium()
    link = _link(uuid.uuid4(), uuid.uuid4(), engine_id=debezium.id)
    uow.dataset_links.get = AsyncMock(return_value=link)
    uow.engines.get = AsyncMock(return_value=debezium)

    with pytest.raises(AppException) as exc:
        await service.render_sql(uow=uow, dataset_link_id=link.id)
    assert exc.value.error_code == errors.ENGINE_NOT_RENDERABLE


@pytest.mark.asyncio
async def test_render_dataset_missing():
    service = EngineRenderService()
    uow = _mk_uow()
    spark = _spark()
    link = _link(uuid.uuid4(), uuid.uuid4(), engine_id=spark.id)
    uow.dataset_links.get = AsyncMock(return_value=link)
    uow.engines.get = AsyncMock(return_value=spark)
    uow.datasets.get = AsyncMock(return_value=None)

    with pytest.raises(AppException) as exc:
        await service.render_sql(uow=uow, dataset_link_id=link.id)
    assert exc.value.error_code == errors.DATASET_NOT_FOUND


@pytest.mark.asyncio
async def test_render_walks_upstream_cdc_for_kafka_source():
    service = EngineRenderService()
    uow = _mk_uow()

    spark = _spark()
    debezium = _debezium()
    kafka_ds = _kafka_dataset(fmt="json")
    hive_ds = _hive_dataset()
    rdbms_id = uuid.uuid4()

    main_link = _link(kafka_ds.id, hive_ds.id, engine_id=spark.id)
    parent_link = _link(rdbms_id, kafka_ds.id, engine_id=debezium.id)

    src_field = _field("amount", kafka_ds.id)
    tgt_field = _field("amount", hive_ds.id, type_code="bigint")
    fl = _field_link(main_link.id, src_field.id, tgt_field.id)

    uow.dataset_links.get = AsyncMock(return_value=main_link)
    uow.dataset_links.list_by_target = AsyncMock(return_value=[parent_link])

    async def _engines_get(eid):
        return {spark.id: spark, debezium.id: debezium}[eid]

    uow.engines.get = AsyncMock(side_effect=_engines_get)

    async def _datasets_get(did):
        return {kafka_ds.id: kafka_ds, hive_ds.id: hive_ds}[did]

    uow.datasets.get = AsyncMock(side_effect=_datasets_get)
    uow.field_links.list_by_dataset_link = AsyncMock(return_value=[fl])

    async def _fields_get(fid):
        return {src_field.id: src_field, tgt_field.id: tgt_field}[fid]

    uow.fields.get = AsyncMock(side_effect=_fields_get)

    result = await service.render_sql(uow=uow, dataset_link_id=main_link.id)
    assert result.engine_kind == "spark"
    # JSON format wraps source field reference in get_json_object(...)
    assert "get_json_object(payload, '$.after.amount')" in result.sql
    assert (
        "CAST(get_json_object(payload, '$.after.amount') AS bigint) AS amount"
        in result.sql
    )


@pytest.mark.asyncio
async def test_render_skips_soft_deleted_upstream_link():
    service = EngineRenderService()
    uow = _mk_uow()
    spark = _spark()
    debezium = _debezium()
    kafka_ds = _kafka_dataset(fmt="avro")
    hive_ds = _hive_dataset()

    main_link = _link(kafka_ds.id, hive_ds.id, engine_id=spark.id)
    soft_deleted_parent = _link(uuid.uuid4(), kafka_ds.id, engine_id=debezium.id)
    soft_deleted_parent.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)

    src_field = _field("id", kafka_ds.id)
    tgt_field = _field("id", hive_ds.id, type_code="bigint")
    fl = _field_link(main_link.id, src_field.id, tgt_field.id)

    uow.dataset_links.get = AsyncMock(return_value=main_link)
    uow.dataset_links.list_by_target = AsyncMock(return_value=[soft_deleted_parent])

    async def _eg(eid):
        return {spark.id: spark, debezium.id: debezium}[eid]

    uow.engines.get = AsyncMock(side_effect=_eg)

    async def _ds_get(did):
        return {kafka_ds.id: kafka_ds, hive_ds.id: hive_ds}[did]

    uow.datasets.get = AsyncMock(side_effect=_ds_get)
    uow.field_links.list_by_dataset_link = AsyncMock(return_value=[fl])

    async def _fields_get(fid):
        return {src_field.id: src_field, tgt_field.id: tgt_field}[fid]

    uow.fields.get = AsyncMock(side_effect=_fields_get)

    result = await service.render_sql(uow=uow, dataset_link_id=main_link.id)
    # Resolver passthrough — no payload. prefix
    assert "payload." not in result.sql
    assert "CAST(id AS bigint) AS id" in result.sql


@pytest.mark.asyncio
async def test_render_no_parent_link_for_kafka_source():
    service = EngineRenderService()
    uow = _mk_uow()
    spark = _spark()
    kafka_ds = _kafka_dataset(fmt="json")
    hive_ds = _hive_dataset()

    main_link = _link(kafka_ds.id, hive_ds.id, engine_id=spark.id)
    src_field = _field("id", kafka_ds.id)
    tgt_field = _field("id", hive_ds.id, type_code="bigint")
    fl = _field_link(main_link.id, src_field.id, tgt_field.id)

    uow.dataset_links.get = AsyncMock(return_value=main_link)
    uow.dataset_links.list_by_target = AsyncMock(return_value=[])
    uow.engines.get = AsyncMock(return_value=spark)

    async def _ds_get(did):
        return {kafka_ds.id: kafka_ds, hive_ds.id: hive_ds}[did]

    uow.datasets.get = AsyncMock(side_effect=_ds_get)
    uow.field_links.list_by_dataset_link = AsyncMock(return_value=[fl])

    async def _fields_get(fid):
        return {src_field.id: src_field, tgt_field.id: tgt_field}[fid]

    uow.fields.get = AsyncMock(side_effect=_fields_get)

    result = await service.render_sql(uow=uow, dataset_link_id=main_link.id)
    # No CDC engine resolved → resolver passthrough
    assert "payload." not in result.sql
    assert "get_json_object" not in result.sql
    assert "CAST(id AS bigint) AS id" in result.sql


@pytest.mark.asyncio
async def test_render_warns_on_broken_field_link():
    service = EngineRenderService()
    uow = _mk_uow()
    spark = _spark()
    kafka_ds = _kafka_dataset()
    hive_ds = _hive_dataset()

    link = _link(kafka_ds.id, hive_ds.id, engine_id=spark.id)
    broken_fl = _field_link(link.id, uuid.uuid4(), uuid.uuid4())

    uow.dataset_links.get = AsyncMock(return_value=link)
    uow.dataset_links.list_by_target = AsyncMock(return_value=[])
    uow.engines.get = AsyncMock(return_value=spark)

    async def _ds_get(did):
        return {kafka_ds.id: kafka_ds, hive_ds.id: hive_ds}[did]

    uow.datasets.get = AsyncMock(side_effect=_ds_get)
    uow.field_links.list_by_dataset_link = AsyncMock(return_value=[broken_fl])
    uow.fields.get = AsyncMock(return_value=None)

    result = await service.render_sql(uow=uow, dataset_link_id=link.id)
    assert any(w.code == "FIELD_LINK_BROKEN" for w in result.warnings)
    # No projections → SELECT * fallback
    assert "SELECT" in result.sql
    assert "*" in result.sql


@pytest.mark.asyncio
async def test_render_dispatches_to_impala():
    service = EngineRenderService()
    uow = _mk_uow()
    impala = _impala()
    # Use non-Kafka source so we skip the upstream walk entirely
    src_ds = _hive_dataset()
    tgt_ds = _hive_dataset()

    link = _link(src_ds.id, tgt_ds.id, engine_id=impala.id)
    src_field = _field("id", src_ds.id)
    tgt_field = _field("id", tgt_ds.id, type_code="bigint")
    fl = _field_link(link.id, src_field.id, tgt_field.id)

    uow.dataset_links.get = AsyncMock(return_value=link)
    uow.engines.get = AsyncMock(return_value=impala)

    async def _ds_get(did):
        return {src_ds.id: src_ds, tgt_ds.id: tgt_ds}[did]

    uow.datasets.get = AsyncMock(side_effect=_ds_get)
    uow.field_links.list_by_dataset_link = AsyncMock(return_value=[fl])

    async def _fields_get(fid):
        return {src_field.id: src_field, tgt_field.id: tgt_field}[fid]

    uow.fields.get = AsyncMock(side_effect=_fields_get)

    result = await service.render_sql(uow=uow, dataset_link_id=link.id)
    assert result.engine_kind == "impala"
    assert "CAST(id AS bigint) AS id" in result.sql
