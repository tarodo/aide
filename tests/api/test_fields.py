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
    Field,
    System,
    SystemFlavor,
    SystemKind,
    User,
)


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="field_super.user@example.com",
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
    kind = SystemKind(code="RDBMS_FIELD_TEST", name="RDBMS for Field Test")
    flavor = SystemFlavor(
        code="PG_FIELD_TEST", name="Postgres for Field Test", kind=kind
    )
    system = System(
        code="PROD_DB_FIELD_TEST", name="Prod DB for Field Test", flavor=flavor
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
        system_id=test_system.id,
        object_name="customers_table_field_test",
        schema_name="public",
        table_name="customers",
    )
    transactional_session.add(dataset)
    await transactional_session.commit()
    await transactional_session.refresh(dataset)
    return dataset


@pytest_asyncio.fixture
async def test_field(
    transactional_session: AsyncSession,
    test_dataset: Dataset,
) -> Field:
    field = Field(
        dataset_id=test_dataset.id,
        name="id",
    )
    transactional_session.add(field)
    await transactional_session.commit()
    await transactional_session.refresh(field)
    return field


@pytest.mark.asyncio
class TestFieldAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_field_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset: Dataset,
    ):
        data = {
            "dataset_id": str(test_dataset.id),
            "name": "email",
            "pii_tags": ["email_address"],
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["name"] == "email"
        assert res_json["pii_tags"] == ["email_address"]

    async def test_create_field_duplicate(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        data = {
            "dataset_id": str(test_field.dataset_id),
            "name": test_field.name,
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.FIELD_ALREADY_EXISTS

    async def test_create_field_dataset_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        data = {
            "dataset_id": str(uuid.uuid4()),
            "name": "some_field",
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.DATASET_NOT_FOUND

    async def test_get_field_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        response = await async_client.get(
            f"/api/v1/fields/{test_field.id}", headers=superuser_token_headers
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_field.id)

    async def test_get_all_fields_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        response = await async_client.get(
            "/api/v1/fields/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_field(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        update_data = {"path": "customer.id"}
        response = await async_client.put(
            f"/api/v1/fields/{test_field.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["path"] == "customer.id"

    async def test_delete_field(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        response = await async_client.delete(
            f"/api/v1/fields/{test_field.id}", headers=superuser_token_headers
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_field.id)

        # Verify it's gone
        response = await async_client.get(
            f"/api/v1/fields/{test_field.id}", headers=superuser_token_headers
        )
        assert response.status_code == 404
