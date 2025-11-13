from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import CredentialRef, User


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    """Fixture for a superuser persisted in the database."""
    user = User(
        email="cr_super.user@example.com",
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
async def test_credential_ref(transactional_session: AsyncSession) -> CredentialRef:
    cr = CredentialRef(provider="vault", path="secrets/data/my-app/db", version=1)
    transactional_session.add(cr)
    await transactional_session.commit()
    await transactional_session.refresh(cr)
    return cr


@pytest.mark.asyncio
class TestCredentialRefAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        """Async client for making API requests."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_credential_ref_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        data = {
            "provider": "aws_secrets_manager",
            "path": "prod/my-app/db-creds",
            "version": None,
        }
        response = await async_client.post(
            "/api/v1/credential-refs/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        assert response.json()["provider"] == "aws_secrets_manager"

    async def test_create_credential_ref_duplicate(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_credential_ref: CredentialRef,
    ):
        data = {
            "provider": test_credential_ref.provider,
            "path": test_credential_ref.path,
        }
        response = await async_client.post(
            "/api/v1/credential-refs/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.CREDENTIAL_REF_ALREADY_EXISTS

    async def test_get_credential_ref_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_credential_ref: CredentialRef,
    ):
        response = await async_client.get(
            f"/api/v1/credential-refs/{test_credential_ref.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_credential_ref.id)

    async def test_get_all_credential_refs_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_credential_ref: CredentialRef,
    ):
        response = await async_client.get(
            "/api/v1/credential-refs/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_credential_ref(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_credential_ref: CredentialRef,
    ):
        update_data = {"version": 2}
        response = await async_client.put(
            f"/api/v1/credential-refs/{test_credential_ref.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["version"] == 2

    async def test_delete_credential_ref(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_credential_ref: CredentialRef,
    ):
        response = await async_client.delete(
            f"/api/v1/credential-refs/{test_credential_ref.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_credential_ref.id)

        # Verify it's gone
        response = await async_client.get(
            f"/api/v1/credential-refs/{test_credential_ref.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
