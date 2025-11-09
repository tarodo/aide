import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.main import app
from backend.models import User


@pytest_asyncio.fixture
async def normal_user(transactional_session: AsyncSession) -> User:
    """Fixture for a normal, active user persisted in the database."""
    user = User(
        email="normal.user@example.com",
        hashed_password=get_password_hash("password123"),
        full_name="Normal User",
        is_active=True,
        is_superuser=False,
    )
    transactional_session.add(user)
    await transactional_session.commit()
    await transactional_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    """Fixture for a superuser persisted in the database."""
    user = User(
        email="super.user@example.com",
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
async def normal_user_token_headers(
    async_client: AsyncClient, normal_user: User
) -> dict[str, str]:
    """Fixture for authentication headers for a normal user."""
    login_data = {"username": normal_user.email, "password": "password123"}
    r = await async_client.post("/api/v1/login/", data=login_data)
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def superuser_token_headers(
    async_client: AsyncClient, superuser: User
) -> dict[str, str]:
    """Fixture for authentication headers for a superuser."""
    login_data = {"username": superuser.email, "password": "password123"}
    r = await async_client.post("/api/v1/login/", data=login_data)
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
class TestUserAPI:
    """
    Tests for the User API endpoints.
    """

    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        """Async client for making API requests."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_user_success(
        self,
        async_client: AsyncClient,
        transactional_session: AsyncSession,
        superuser_token_headers: dict,
    ):
        """
        Test creating a user successfully (requires superuser).
        """
        user_data = {
            "email": "test.create@example.com",
            "password": "a_secure_password",
            "full_name": "Test Create User",
        }

        response = await async_client.post(
            "/api/v1/users/", json=user_data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        response_data = response.json()
        assert response_data["email"] == user_data["email"]
        user_id = response_data["id"]

        db_user = await transactional_session.get(User, uuid.UUID(user_id))
        assert db_user is not None
        assert db_user.email == user_data["email"]

    async def test_create_user_unauthorized(self, async_client: AsyncClient):
        """Test creating a user without authentication fails."""
        user_data = {"email": "unauth@example.com", "password": "password"}
        response = await async_client.post("/api/v1/users/", json=user_data)
        assert response.status_code == 401

    async def test_create_user_forbidden_for_normal_user(
        self, async_client: AsyncClient, normal_user_token_headers: dict
    ):
        """Test creating a user as a normal user fails."""
        user_data = {"email": "forbidden@example.com", "password": "password"}
        response = await async_client.post(
            "/api/v1/users/", json=user_data, headers=normal_user_token_headers
        )
        assert response.status_code == 403

    async def test_create_user_duplicate_email(
        self, async_client: AsyncClient, superuser_token_headers: dict
    ):
        """
        Test creating a user with a duplicate email fails.
        """
        user_data = {
            "email": "duplicate.email@example.com",
            "password": "password123",
        }
        response = await async_client.post(
            "/api/v1/users/", json=user_data, headers=superuser_token_headers
        )
        assert response.status_code == 201

        response = await async_client.post(
            "/api/v1/users/", json=user_data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    async def test_get_user_by_id_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        normal_user: User,
    ):
        """Test getting a user by ID successfully."""
        response = await async_client.get(
            f"/api/v1/users/{normal_user.id}", headers=superuser_token_headers
        )
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["id"] == str(normal_user.id)
        assert response_data["email"] == normal_user.email

    async def test_get_user_by_id_unauthorized(
        self, async_client: AsyncClient, normal_user: User
    ):
        """Test getting a user by ID without authentication fails."""
        response = await async_client.get(f"/api/v1/users/{normal_user.id}")
        assert response.status_code == 401

    async def test_get_user_not_found(
        self, async_client: AsyncClient, superuser_token_headers: dict
    ):
        """Test getting a non-existent user by ID."""
        non_existent_uuid = uuid.uuid4()
        response = await async_client.get(
            f"/api/v1/users/{non_existent_uuid}", headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"

    async def test_get_me_success(
        self,
        async_client: AsyncClient,
        normal_user: User,
        normal_user_token_headers: dict,
    ):
        """
        Test the /me endpoint successfully returns the current user.
        """
        response = await async_client.get(
            "/api/v1/users/me", headers=normal_user_token_headers
        )
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["id"] == str(normal_user.id)
        assert response_data["email"] == normal_user.email

    async def test_get_me_unauthorized(self, async_client: AsyncClient):
        """Test the /me endpoint without authentication fails."""
        response = await async_client.get("/api/v1/users/me")
        assert response.status_code == 401
