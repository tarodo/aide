from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import DataType, SystemFlavor, SystemKind, User


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    """Fixture for a superuser persisted in the database."""
    user = User(
        email="dt_super.user@example.com",
        hashed_password=get_password_hash("password123"),
        full_name="Super User",
        is_active=True,
        is_superuser=True,
    )
    transactional_session.add(user)
    await transactional_session.commit()
    await transactional_session.refresh(user)
    return user


@pytest.fixture
async def superuser_token_headers(
    async_client: AsyncClient, superuser: User
) -> dict[str, str]:
    """Fixture for authentication headers for a superuser."""
    login_data = {"username": superuser.email, "password": "password123"}
    r = await async_client.post("/api/v1/login/", data=login_data)
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_system_kind(transactional_session: AsyncSession) -> SystemKind:
    sk = SystemKind(code="RDBMS_DT", name="Relational Database for DT")
    transactional_session.add(sk)
    await transactional_session.commit()
    await transactional_session.refresh(sk)
    return sk


@pytest_asyncio.fixture
async def test_system_flavor(
    transactional_session: AsyncSession, test_system_kind: SystemKind
) -> SystemFlavor:
    sf = SystemFlavor(
        code="POSTGRESQL_DT", name="PostgreSQL for DT", kind_id=test_system_kind.id
    )
    transactional_session.add(sf)
    await transactional_session.commit()
    await transactional_session.refresh(sf)
    return sf


@pytest_asyncio.fixture
async def test_data_type(
    transactional_session: AsyncSession, test_system_flavor: SystemFlavor
) -> DataType:
    dt = DataType(
        system_flavor_id=test_system_flavor.id,
        code="VARCHAR",
        params_schema={"length": {"type": "integer"}},
    )
    transactional_session.add(dt)
    await transactional_session.commit()
    await transactional_session.refresh(dt)
    return dt


@pytest.mark.asyncio
class TestDataTypeAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        """Async client for making API requests."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_data_type_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system_flavor: SystemFlavor,
    ):
        data = {
            "system_flavor_id": str(test_system_flavor.id),
            "code": "INTEGER",
            "params_schema": {},
        }
        response = await async_client.post(
            "/api/v1/data-types/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        assert response.json()["code"] == "INTEGER"

    async def test_create_data_type_duplicate(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_type: DataType,
    ):
        data = {
            "system_flavor_id": str(test_data_type.system_flavor_id),
            "code": test_data_type.code,
            "params_schema": {},
        }
        response = await async_client.post(
            "/api/v1/data-types/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.DATA_TYPE_ALREADY_EXISTS

    async def test_get_data_type_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_type: DataType,
    ):
        response = await async_client.get(
            f"/api/v1/data-types/{test_data_type.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_data_type.id)

    async def test_get_all_data_types_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_type: DataType,
    ):
        response = await async_client.get(
            "/api/v1/data-types/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_data_type(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_type: DataType,
    ):
        update_data = {"code": "TEXT"}
        response = await async_client.put(
            f"/api/v1/data-types/{test_data_type.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["code"] == "TEXT"

    async def test_delete_data_type(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_type: DataType,
    ):
        response = await async_client.delete(
            f"/api/v1/data-types/{test_data_type.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_data_type.id)

        # Verify it's gone
        response = await async_client.get(
            f"/api/v1/data-types/{test_data_type.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
