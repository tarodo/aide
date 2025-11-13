from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import CredentialRef, System, SystemFlavor, SystemKind, User


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    """Fixture for a superuser persisted in the database."""
    user = User(
        email="sys_super.user@example.com",
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
    sk = SystemKind(code="RDBMS_SYS", name="Relational Database for Systems")
    transactional_session.add(sk)
    await transactional_session.commit()
    await transactional_session.refresh(sk)
    return sk


@pytest_asyncio.fixture
async def test_system_flavor(
    transactional_session: AsyncSession, test_system_kind: SystemKind
) -> SystemFlavor:
    sf = SystemFlavor(
        code="POSTGRESQL_SYS",
        name="PostgreSQL for Systems",
        kind_id=test_system_kind.id,
    )
    transactional_session.add(sf)
    await transactional_session.commit()
    await transactional_session.refresh(sf)
    return sf


@pytest_asyncio.fixture
async def test_credential_ref(transactional_session: AsyncSession) -> CredentialRef:
    cr = CredentialRef(provider="vault_sys", path="secrets/data/my-app/db_sys")
    transactional_session.add(cr)
    await transactional_session.commit()
    await transactional_session.refresh(cr)
    return cr


@pytest_asyncio.fixture
async def test_system(
    transactional_session: AsyncSession,
    test_system_flavor: SystemFlavor,
    test_credential_ref: CredentialRef,
) -> System:
    s = System(
        code="PROD_DB",
        name="Production Database",
        flavor_id=test_system_flavor.id,
        credential_ref_id=test_credential_ref.id,
    )
    transactional_session.add(s)
    await transactional_session.commit()
    await transactional_session.refresh(s)
    return s


@pytest.mark.asyncio
class TestSystemAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        """Async client for making API requests."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_system_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system_flavor: SystemFlavor,
        test_credential_ref: CredentialRef,
    ):
        data = {
            "code": "STAGING_DB",
            "name": "Staging Database",
            "flavor_id": str(test_system_flavor.id),
            "credential_ref_id": str(test_credential_ref.id),
            "is_active": True,
            "tags": ["staging", "postgres"],
        }
        response = await async_client.post(
            "/api/v1/systems/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["code"] == "STAGING_DB"
        assert res_json["tags"] == ["staging", "postgres"]

    async def test_create_system_duplicate(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        data = {
            "code": test_system.code,
            "name": "Another Prod DB",
            "flavor_id": str(test_system.flavor_id),
        }
        response = await async_client.post(
            "/api/v1/systems/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.SYSTEM_ALREADY_EXISTS

    async def test_get_system_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        response = await async_client.get(
            f"/api/v1/systems/{test_system.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_system.id)

    async def test_get_all_systems_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        response = await async_client.get(
            "/api/v1/systems/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_system(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        update_data = {"name": "Updated Production DB", "is_active": False}
        response = await async_client.put(
            f"/api/v1/systems/{test_system.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["name"] == "Updated Production DB"
        assert res_json["is_active"] is False

    async def test_delete_system(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        response = await async_client.delete(
            f"/api/v1/systems/{test_system.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_system.id)

        # Verify it's gone
        response = await async_client.get(
            f"/api/v1/systems/{test_system.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
