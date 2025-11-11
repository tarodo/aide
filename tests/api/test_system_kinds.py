from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import SystemKind, User


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    """Fixture for a superuser persisted in the database."""
    user = User(
        email="sk_super.user@example.com",
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
    sk = SystemKind(code="RDBMS", name="Relational Database")
    transactional_session.add(sk)
    await transactional_session.commit()
    await transactional_session.refresh(sk)
    return sk


@pytest.mark.asyncio
class TestSystemKindAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        """Async client for making API requests."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_system_kind_success(
        self, async_client: AsyncClient, superuser_token_headers: dict
    ):
        data = {"code": "KAFKA", "name": "Apache Kafka"}
        response = await async_client.post(
            "/api/v1/system_kinds/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        assert response.json()["code"] == "KAFKA"

    async def test_create_system_kind_duplicate(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system_kind: SystemKind,
    ):
        data = {"code": test_system_kind.code, "name": "Another RDBMS"}
        response = await async_client.post(
            "/api/v1/system_kinds/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.SYSTEM_KIND_ALREADY_EXISTS

    async def test_get_system_kind_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system_kind: SystemKind,
    ):
        response = await async_client.get(
            f"/api/v1/system_kinds/{test_system_kind.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_system_kind.id)

    async def test_get_all_system_kinds_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system_kind: SystemKind,
    ):
        response = await async_client.get(
            "/api/v1/system_kinds/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_system_kind(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system_kind: SystemKind,
    ):
        update_data = {"name": "Updated RDBMS Name"}
        response = await async_client.put(
            f"/api/v1/system_kinds/{test_system_kind.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated RDBMS Name"
        assert response.json()["code"] == test_system_kind.code

    async def test_delete_system_kind(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system_kind: SystemKind,
    ):
        response = await async_client.delete(
            f"/api/v1/system_kinds/{test_system_kind.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_system_kind.id)

        # Verify it's gone
        response = await async_client.get(
            f"/api/v1/system_kinds/{test_system_kind.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
