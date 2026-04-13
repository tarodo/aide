import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import (
    Dataset,
    DatasetRdbms,
    DatasetSchema,
    System,
    SystemFlavor,
    SystemKind,
    User,
)


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="ds_schema_super.user@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
        is_superuser=True,
    )
    transactional_session.add(user)
    await transactional_session.commit()
    return user


@pytest.fixture
async def superuser_token_headers(
    async_client: AsyncClient, superuser: User
) -> dict[str, str]:
    login_data = {"username": superuser.email, "password": "password123"}
    r = await async_client.post("/api/v1/login/", data=login_data)
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_system(transactional_session: AsyncSession) -> System:
    kind = SystemKind(code="RDBMS_DS_SCHEMA_TEST", name="RDBMS for DS Schema Test")
    flavor = SystemFlavor(
        code="PG_DS_SCHEMA_TEST", name="Postgres for DS Schema Test", kind=kind
    )
    system = System(
        code="PROD_DB_DS_SCHEMA_TEST", name="Prod DB for DS Schema Test", flavor=flavor
    )
    transactional_session.add_all([kind, flavor, system])
    await transactional_session.commit()
    await transactional_session.refresh(system)
    return system


@pytest_asyncio.fixture
async def test_dataset(
    transactional_session: AsyncSession, test_system: System
) -> Dataset:
    dataset = DatasetRdbms(
        system=test_system,
        object_name="customers_table_ds_schema_test",
        schema_name="public",
        table_name="customers",
    )
    transactional_session.add(dataset)
    await transactional_session.commit()
    await transactional_session.refresh(dataset)
    return dataset


@pytest_asyncio.fixture
async def test_dataset_schema(
    transactional_session: AsyncSession,
    test_dataset: Dataset,
) -> DatasetSchema:
    schema = DatasetSchema(
        dataset=test_dataset,
        version_num=1,
        schema={"type": "struct", "fields": []},
    )
    transactional_session.add(schema)
    await transactional_session.commit()
    await transactional_session.refresh(schema)
    return schema


@pytest.mark.asyncio
class TestDatasetSchemaAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_dataset_schema_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset: Dataset,
    ):
        data = {
            "dataset_id": str(test_dataset.id),
            "version_num": 1,
            "schema": {"type": "struct", "fields": [{"name": "id", "type": "int"}]},
        }
        response = await async_client.post(
            "/api/v1/dataset-schemas/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["version_num"] == 1
        assert res_json["schema_"]["fields"][0]["name"] == "id"

    async def test_create_dataset_schema_duplicate(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset_schema: DatasetSchema,
    ):
        data = {
            "dataset_id": str(test_dataset_schema.dataset_id),
            "version_num": test_dataset_schema.version_num,
            "schema": {},
        }
        response = await async_client.post(
            "/api/v1/dataset-schemas/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.DATASET_SCHEMA_ALREADY_EXISTS

    async def test_create_dataset_schema_dataset_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        data = {
            "dataset_id": str(uuid.uuid4()),
            "version_num": 1,
            "schema": {},
        }
        response = await async_client.post(
            "/api/v1/dataset-schemas/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.DATASET_NOT_FOUND

    async def test_get_dataset_schema_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset_schema: DatasetSchema,
    ):
        response = await async_client.get(
            f"/api/v1/dataset-schemas/{test_dataset_schema.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_dataset_schema.id)

    async def test_get_all_dataset_schemas_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset_schema: DatasetSchema,
    ):
        response = await async_client.get(
            "/api/v1/dataset-schemas/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_dataset_schema(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset_schema: DatasetSchema,
    ):
        update_data = {"extra": {"comment": "first version"}, "row_version": 1}
        response = await async_client.put(
            f"/api/v1/dataset-schemas/{test_dataset_schema.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["extra"]["comment"] == "first version"

    async def test_delete_dataset_schema(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset_schema: DatasetSchema,
    ):
        response = await async_client.delete(
            f"/api/v1/dataset-schemas/{test_dataset_schema.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_dataset_schema.id)

        # Verify it's gone
        response = await async_client.get(
            f"/api/v1/dataset-schemas/{test_dataset_schema.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
