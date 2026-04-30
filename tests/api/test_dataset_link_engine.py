from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.main import app
from backend.models import (
    DatasetHive,
    DatasetKafka,
    DatasetLink,
    DatasetRdbms,
    DatasetSchema,
    Field,
    FieldLink,
    System,
    SystemFlavor,
    SystemKind,
    User,
)
from backend.models.engine import EngineDebezium, EngineSpark


@pytest.mark.asyncio
class TestDatasetLinkEngineAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    @pytest_asyncio.fixture
    async def superuser(self, transactional_session: AsyncSession) -> User:
        user = User(
            email="dl_engine_super@example.com",
            hashed_password=get_password_hash("password123"),
            is_active=True,
            is_superuser=True,
        )
        transactional_session.add(user)
        await transactional_session.commit()
        return user

    @pytest_asyncio.fixture
    async def headers(
        self, async_client: AsyncClient, superuser: User
    ) -> dict[str, str]:
        r = await async_client.post(
            "/api/v1/login/",
            data={"username": superuser.email, "password": "password123"},
        )
        token = r.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    @pytest_asyncio.fixture
    async def kafka_to_hive_link(
        self, transactional_session: AsyncSession
    ) -> DatasetLink:
        kind = SystemKind(code="DLE_KIND", name="kind")
        kafka_flavor = SystemFlavor(code="DLE_KAFKA", name="kafka", kind=kind)
        hive_flavor = SystemFlavor(code="DLE_HIVE", name="hive", kind=kind)
        kafka_sys = System(code="DLE_KAFKA_SYS", name="kafka sys", flavor=kafka_flavor)
        hive_sys = System(code="DLE_HIVE_SYS", name="hive sys", flavor=hive_flavor)
        transactional_session.add_all(
            [kind, kafka_flavor, hive_flavor, kafka_sys, hive_sys]
        )
        await transactional_session.flush()

        kafka_ds = DatasetKafka(
            system_id=kafka_sys.id,
            object_name="dle_kafka_topic",
            kind="kafka",
            layer="kafka",
            topic="dle_kafka_topic",
            format="json",
            partitions=1,
            retention_ms=86400000,
            key_columns=["id"],
        )
        hive_ds = DatasetHive(
            system_id=hive_sys.id,
            object_name="dle_hive_table",
            kind="hive",
            layer="raw",
            catalog_uri="thrift://hms",
            db_name="raw",
            table_name="dle_hive_table",
            file_format="parquet",
        )
        transactional_session.add_all([kafka_ds, hive_ds])
        await transactional_session.flush()

        kafka_schema = DatasetSchema(dataset_id=kafka_ds.id, version_num=1, schema={})
        hive_schema = DatasetSchema(dataset_id=hive_ds.id, version_num=1, schema={})
        transactional_session.add_all([kafka_schema, hive_schema])
        await transactional_session.flush()

        link = DatasetLink(
            source_dataset_id=kafka_ds.id,
            target_dataset_id=hive_ds.id,
            source_schema_id=kafka_schema.id,
            target_schema_id=hive_schema.id,
        )
        transactional_session.add(link)
        await transactional_session.commit()
        await transactional_session.refresh(link)
        return link

    @pytest_asyncio.fixture
    async def spark_engine(self, transactional_session: AsyncSession) -> EngineSpark:
        eng = EngineSpark(
            code="dle_spark",
            name="DLE Spark",
            kind="spark",
            role="compute",
            version="3.x",
        )
        transactional_session.add(eng)
        await transactional_session.commit()
        await transactional_session.refresh(eng)
        return eng

    @pytest_asyncio.fixture
    async def debezium_engine(
        self, transactional_session: AsyncSession
    ) -> EngineDebezium:
        eng = EngineDebezium(
            code="dle_dbz",
            name="DLE Debezium",
            kind="debezium",
            role="cdc",
            version="2.x",
            envelope_template={
                "envelope_kind": "debezium",
                "after_path": "after",
                "before_path": "before",
                "op_path": "op",
                "ts_ms_path": "ts_ms",
            },
        )
        transactional_session.add(eng)
        await transactional_session.commit()
        await transactional_session.refresh(eng)
        return eng

    async def test_attach_compute_engine_succeeds(
        self,
        async_client: AsyncClient,
        headers: dict,
        kafka_to_hive_link: DatasetLink,
        spark_engine: EngineSpark,
    ):
        resp = await async_client.patch(
            f"/api/v1/dataset-links/{kafka_to_hive_link.id}",
            headers=headers,
            json={"engine_id": str(spark_engine.id), "row_version": 1},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["engine_id"] == str(spark_engine.id)

    async def test_attach_engine_incompatible_returns_409(
        self,
        async_client: AsyncClient,
        headers: dict,
        kafka_to_hive_link: DatasetLink,
        debezium_engine: EngineDebezium,
    ):
        resp = await async_client.patch(
            f"/api/v1/dataset-links/{kafka_to_hive_link.id}",
            headers=headers,
            json={"engine_id": str(debezium_engine.id), "row_version": 1},
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["error_code"] == "ENGINE_INCOMPATIBLE_LINK"
        assert "details" in body

    async def test_render_no_engine_attached_409(
        self,
        async_client: AsyncClient,
        headers: dict,
        kafka_to_hive_link: DatasetLink,
    ):
        resp = await async_client.post(
            f"/api/v1/dataset-links/{kafka_to_hive_link.id}/render-sql",
            headers=headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "ENGINE_NOT_ATTACHED"

    async def test_render_with_compute_engine_returns_sql(
        self,
        async_client: AsyncClient,
        headers: dict,
        kafka_to_hive_link: DatasetLink,
        spark_engine: EngineSpark,
        transactional_session: AsyncSession,
    ):
        # Attach engine and add one FieldLink
        kafka_to_hive_link.engine_id = spark_engine.id
        src_field = Field(
            dataset_id=kafka_to_hive_link.source_dataset_id,
            name="id",
            origin="mapped",
        )
        tgt_field = Field(
            dataset_id=kafka_to_hive_link.target_dataset_id,
            name="id",
            origin="mapped",
            extra={"data_type_code": "bigint"},
        )
        transactional_session.add_all([src_field, tgt_field])
        await transactional_session.flush()
        fl = FieldLink(
            dataset_link_id=kafka_to_hive_link.id,
            source_field_id=src_field.id,
            target_field_id=tgt_field.id,
        )
        transactional_session.add(fl)
        await transactional_session.commit()

        resp = await async_client.post(
            f"/api/v1/dataset-links/{kafka_to_hive_link.id}/render-sql",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["engine_kind"] == "spark"
        assert "INSERT INTO" in body["sql"]
        assert "CAST(id AS bigint) AS id" in body["sql"]

    async def test_render_with_cdc_engine_returns_409(
        self,
        async_client: AsyncClient,
        headers: dict,
        transactional_session: AsyncSession,
        debezium_engine: EngineDebezium,
    ):
        # Build an rdbms->kafka link, attach the CDC engine, then attempt render
        kind = SystemKind(code="DLE_RDBMS_KIND", name="kind")
        rdbms_flavor = SystemFlavor(code="DLE_RDBMS", name="rdbms", kind=kind)
        kafka_flavor = SystemFlavor(code="DLE_KAFKA2", name="kafka", kind=kind)
        rdbms_sys = System(code="DLE_RDBMS_SYS", name="rdbms sys", flavor=rdbms_flavor)
        kafka_sys = System(code="DLE_KAFKA2_SYS", name="kafka sys", flavor=kafka_flavor)
        transactional_session.add_all(
            [kind, rdbms_flavor, kafka_flavor, rdbms_sys, kafka_sys]
        )
        await transactional_session.flush()

        rdbms_ds = DatasetRdbms(
            system_id=rdbms_sys.id,
            object_name="dle_rdbms_t",
            kind="rdbms",
            layer="source",
            schema_name="public",
            table_name="t",
        )
        kafka_ds = DatasetKafka(
            system_id=kafka_sys.id,
            object_name="dle_cdc_topic",
            kind="kafka",
            layer="cdc",
            topic="dle_cdc_topic",
            format="json",
            partitions=1,
            retention_ms=86400000,
            key_columns=["id"],
        )
        transactional_session.add_all([rdbms_ds, kafka_ds])
        await transactional_session.flush()
        rdbms_schema = DatasetSchema(dataset_id=rdbms_ds.id, version_num=1, schema={})
        kafka_schema = DatasetSchema(dataset_id=kafka_ds.id, version_num=1, schema={})
        transactional_session.add_all([rdbms_schema, kafka_schema])
        await transactional_session.flush()

        link = DatasetLink(
            source_dataset_id=rdbms_ds.id,
            target_dataset_id=kafka_ds.id,
            source_schema_id=rdbms_schema.id,
            target_schema_id=kafka_schema.id,
            engine_id=debezium_engine.id,
        )
        transactional_session.add(link)
        await transactional_session.commit()

        resp = await async_client.post(
            f"/api/v1/dataset-links/{link.id}/render-sql",
            headers=headers,
        )
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "ENGINE_NOT_RENDERABLE"
