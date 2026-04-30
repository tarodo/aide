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
    DatasetSchema,
    System,
    SystemFlavor,
    SystemKind,
    User,
)
from backend.models.engine import EngineDebezium, EngineSpark


@pytest.mark.asyncio
class TestEnginesAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    @pytest_asyncio.fixture
    async def superuser(self, transactional_session: AsyncSession) -> User:
        user = User(
            email="engines_super@example.com",
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
    async def spark_engine_row(
        self, transactional_session: AsyncSession
    ) -> EngineSpark:
        eng = EngineSpark(
            code="api-existing-spark",
            name="Existing Spark",
            kind="spark",
            role="compute",
            version="3.x",
        )
        transactional_session.add(eng)
        await transactional_session.commit()
        await transactional_session.refresh(eng)
        return eng

    @pytest_asyncio.fixture
    async def debezium_engine_row(
        self, transactional_session: AsyncSession
    ) -> EngineDebezium:
        eng = EngineDebezium(
            code="api-existing-dbz",
            name="Existing Debezium",
            kind="debezium",
            role="cdc",
            version="2.x",
            envelope_template={
                "envelope_kind": "debezium",
                "after_path": "after",
            },
        )
        transactional_session.add(eng)
        await transactional_session.commit()
        await transactional_session.refresh(eng)
        return eng

    async def test_create_spark_engine(self, async_client: AsyncClient, headers: dict):
        resp = await async_client.post(
            "/api/v1/engines/",
            headers=headers,
            json={
                "kind": "spark",
                "code": "api-spark-1",
                "name": "API Spark 1",
                "version": "3.x",
                "runtime_opts": {"output_mode": "append"},
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["kind"] == "spark"
        assert body["role"] == "compute"
        assert body["runtime_opts"]["output_mode"] == "append"

    async def test_create_engine_duplicate_code_returns_409(
        self,
        async_client: AsyncClient,
        headers: dict,
        spark_engine_row: EngineSpark,
    ):
        resp = await async_client.post(
            "/api/v1/engines/",
            headers=headers,
            json={
                "kind": "spark",
                "code": spark_engine_row.code,
                "name": "dup",
                "version": "3.x",
            },
        )
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "ENGINE_CODE_ALREADY_EXISTS"

    async def test_create_engine_invalid_version_returns_422(
        self, async_client: AsyncClient, headers: dict
    ):
        resp = await async_client.post(
            "/api/v1/engines/",
            headers=headers,
            json={
                "kind": "spark",
                "code": "api-spark-bad",
                "name": "bad",
                "version": "2.x",  # not in {"3.x", "4.x"}
            },
        )
        assert resp.status_code == 422

    async def test_list_filter_by_role(
        self,
        async_client: AsyncClient,
        headers: dict,
        spark_engine_row: EngineSpark,
        debezium_engine_row: EngineDebezium,
    ):
        resp = await async_client.get("/api/v1/engines/?role=cdc", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        codes = {item["code"] for item in body["items"]}
        assert debezium_engine_row.code in codes
        assert spark_engine_row.code not in codes

    async def test_patch_kind_change_rejected(
        self,
        async_client: AsyncClient,
        headers: dict,
        spark_engine_row: EngineSpark,
    ):
        resp = await async_client.patch(
            f"/api/v1/engines/{spark_engine_row.id}",
            headers=headers,
            json={"kind": "impala", "name": "renamed", "row_version": 1},
        )
        # Pydantic discriminated-union dispatch sees kind="impala" and validates
        # against EngineImpalaUpdate; the route reaches the service which then
        # raises ENGINE_KIND_IMMUTABLE because the DB row has kind="spark".
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "ENGINE_KIND_IMMUTABLE"

    async def test_delete_engine_in_use_returns_409(
        self,
        async_client: AsyncClient,
        headers: dict,
        transactional_session: AsyncSession,
        spark_engine_row: EngineSpark,
    ):
        # Build a kafka->hive link that references the spark engine
        kind = SystemKind(code="ENG_DEL_KIND", name="kind")
        kafka_flavor = SystemFlavor(code="ENG_DEL_KAFKA", name="kafka", kind=kind)
        hive_flavor = SystemFlavor(code="ENG_DEL_HIVE", name="hive", kind=kind)
        kafka_sys = System(code="ENG_DEL_KAFKA_SYS", name="ks", flavor=kafka_flavor)
        hive_sys = System(code="ENG_DEL_HIVE_SYS", name="hs", flavor=hive_flavor)
        transactional_session.add_all(
            [kind, kafka_flavor, hive_flavor, kafka_sys, hive_sys]
        )
        await transactional_session.flush()

        kafka_ds = DatasetKafka(
            system_id=kafka_sys.id,
            object_name="del_kafka",
            kind="kafka",
            layer="kafka",
            topic="del_kafka",
            format="json",
            partitions=1,
            retention_ms=86400000,
            key_columns=["id"],
        )
        hive_ds = DatasetHive(
            system_id=hive_sys.id,
            object_name="del_hive",
            kind="hive",
            layer="raw",
            catalog_uri="thrift://hms",
            db_name="raw",
            table_name="del_hive",
            file_format="parquet",
        )
        transactional_session.add_all([kafka_ds, hive_ds])
        await transactional_session.flush()

        kschema = DatasetSchema(dataset_id=kafka_ds.id, version_num=1, schema={})
        hschema = DatasetSchema(dataset_id=hive_ds.id, version_num=1, schema={})
        transactional_session.add_all([kschema, hschema])
        await transactional_session.flush()

        link = DatasetLink(
            source_dataset_id=kafka_ds.id,
            target_dataset_id=hive_ds.id,
            source_schema_id=kschema.id,
            target_schema_id=hschema.id,
            engine_id=spark_engine_row.id,
        )
        transactional_session.add(link)
        await transactional_session.commit()

        resp = await async_client.delete(
            f"/api/v1/engines/{spark_engine_row.id}", headers=headers
        )
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "ENGINE_IN_USE"
