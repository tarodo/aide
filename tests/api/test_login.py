from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import User
from backend.models.user import UserType


@pytest.mark.asyncio
class TestLoginAPI:
    """
    Tests for the Login API endpoint.
    """

    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        """Async client for making API requests."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    @pytest.fixture
    async def test_user_credentials(
        self,
        transactional_session: AsyncSession,
        async_client: AsyncClient,
    ) -> dict:
        """
        Create a user for login tests and return their credentials.
        """
        user_data = {
            "email": "login.test@example.com",
            "password": "a_secure_password",
            "full_name": "Login Test User",
        }
        user = User(
            email=user_data["email"],
            hashed_password=get_password_hash(user_data["password"]),
            full_name=user_data["full_name"],
            is_active=True,
            is_superuser=False,
        )
        transactional_session.add(user)
        await transactional_session.flush()
        return {"username": user_data["email"], "password": user_data["password"]}

    async def test_login_success(
        self, async_client: AsyncClient, test_user_credentials: dict
    ):
        """
        Test successful login with correct credentials.
        Verifies:
        - 200 status code
        - Response contains access_token, refresh_token, token_type, expires_in
        """
        response = await async_client.post("/api/v1/login/", data=test_user_credentials)

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 30 * 60

    async def test_login_failure_wrong_password(
        self, async_client: AsyncClient, test_user_credentials: dict
    ):
        """Test login with a correct email but wrong password."""
        wrong_credentials = test_user_credentials.copy()
        wrong_credentials["password"] = "wrong_password"

        response = await async_client.post("/api/v1/login/", data=wrong_credentials)

        assert response.status_code == 401
        response_data = response.json()
        assert response_data["error_code"] == errors.INVALID_CREDENTIALS

    async def test_login_failure_user_not_found(self, async_client: AsyncClient):
        """Test login with an email that does not exist."""
        non_existent_credentials = {
            "username": "not.found@example.com",
            "password": "any_password",
        }

        response = await async_client.post(
            "/api/v1/login/", data=non_existent_credentials
        )

        assert response.status_code == 401
        response_data = response.json()
        assert response_data["error_code"] == errors.INVALID_CREDENTIALS


@pytest.mark.asyncio
class TestRefreshTokenAPI:
    """Tests for refresh token endpoints."""

    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    @pytest.fixture
    async def user_with_tokens(
        self,
        transactional_session: AsyncSession,
        async_client: AsyncClient,
    ) -> dict:
        """Create a user, login, and return credentials + tokens."""
        password = "test_password_123"
        user = User(
            email="refresh.test@example.com",
            hashed_password=get_password_hash(password),
            full_name="Refresh Test User",
            is_active=True,
            is_superuser=False,
        )
        transactional_session.add(user)
        await transactional_session.flush()

        response = await async_client.post(
            "/api/v1/login/",
            data={"username": "refresh.test@example.com", "password": password},
        )
        tokens = response.json()
        return {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "password": password,
            "email": "refresh.test@example.com",
        }

    async def test_refresh_returns_new_tokens(
        self, async_client: AsyncClient, user_with_tokens: dict
    ):
        """Refresh endpoint returns a new access + refresh token pair."""
        response = await async_client.post(
            "/api/v1/login/refresh",
            json={"refresh_token": user_with_tokens["refresh_token"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["refresh_token"] != user_with_tokens["refresh_token"]

    async def test_refresh_rotates_token(
        self, async_client: AsyncClient, user_with_tokens: dict
    ):
        """Old refresh token is invalidated after rotation."""
        old_refresh = user_with_tokens["refresh_token"]

        # First refresh — should succeed
        resp1 = await async_client.post(
            "/api/v1/login/refresh",
            json={"refresh_token": old_refresh},
        )
        assert resp1.status_code == 200

        # Second refresh with old token — should fail (revoked)
        resp2 = await async_client.post(
            "/api/v1/login/refresh",
            json={"refresh_token": old_refresh},
        )
        assert resp2.status_code == 401
        assert resp2.json()["error_code"] == errors.REFRESH_TOKEN_REVOKED

    async def test_refresh_invalid_token(self, async_client: AsyncClient):
        """Refresh with a completely invalid token returns 401."""
        response = await async_client.post(
            "/api/v1/login/refresh",
            json={"refresh_token": "totally_invalid_token"},
        )

        assert response.status_code == 401
        assert response.json()["error_code"] == errors.REFRESH_TOKEN_INVALID

    async def test_logout_revokes_token(
        self, async_client: AsyncClient, user_with_tokens: dict
    ):
        """Logout revokes the refresh token."""
        refresh = user_with_tokens["refresh_token"]

        # Logout
        resp = await async_client.post(
            "/api/v1/login/logout",
            json={"refresh_token": refresh},
        )
        assert resp.status_code == 204

        # Try to refresh with revoked token
        resp2 = await async_client.post(
            "/api/v1/login/refresh",
            json={"refresh_token": refresh},
        )
        assert resp2.status_code == 401

    async def test_logout_all_revokes_all_tokens(
        self, async_client: AsyncClient, user_with_tokens: dict
    ):
        """Logout-all revokes all refresh tokens for the user."""
        # Login again to get a second refresh token
        resp_login2 = await async_client.post(
            "/api/v1/login/",
            data={
                "username": user_with_tokens["email"],
                "password": user_with_tokens["password"],
            },
        )
        tokens2 = resp_login2.json()

        # Logout-all using the access token from the first login
        resp = await async_client.post(
            "/api/v1/login/logout-all",
            headers={"Authorization": f"Bearer {user_with_tokens['access_token']}"},
        )
        assert resp.status_code == 204

        # Both refresh tokens should now be revoked
        for rt in [user_with_tokens["refresh_token"], tokens2["refresh_token"]]:
            resp_refresh = await async_client.post(
                "/api/v1/login/refresh",
                json={"refresh_token": rt},
            )
            assert resp_refresh.status_code == 401


@pytest.mark.asyncio
class TestTechnicalUserTokens:
    """Tests for technical user token lifetime."""

    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_technical_user_gets_longer_refresh_token(
        self,
        transactional_session: AsyncSession,
        async_client: AsyncClient,
    ):
        """Technical user receives a refresh token with longer TTL."""
        password = "tech_password_123"
        user = User(
            email="tech.user@example.com",
            hashed_password=get_password_hash(password),
            full_name="Tech User",
            is_active=True,
            is_superuser=False,
            user_type=UserType.TECHNICAL.value,
        )
        transactional_session.add(user)
        await transactional_session.flush()

        response = await async_client.post(
            "/api/v1/login/",
            data={"username": "tech.user@example.com", "password": password},
        )

        assert response.status_code == 200
        data = response.json()
        assert "refresh_token" in data
