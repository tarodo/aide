from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import User


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
        - Response contains 'access_token' and 'token_type'
        """
        # Act
        response = await async_client.post("/api/v1/login/", data=test_user_credentials)

        # Assert
        assert response.status_code == 200
        response_data = response.json()
        assert "access_token" in response_data
        assert response_data["token_type"] == "bearer"

    async def test_login_failure_wrong_password(
        self, async_client: AsyncClient, test_user_credentials: dict
    ):
        """Test login with a correct email but wrong password."""
        # Arrange
        wrong_credentials = test_user_credentials.copy()
        wrong_credentials["password"] = "wrong_password"

        # Act
        response = await async_client.post("/api/v1/login/", data=wrong_credentials)

        # Assert
        assert response.status_code == 401
        response_data = response.json()
        assert response_data["error_code"] == errors.INVALID_CREDENTIALS

    async def test_login_failure_user_not_found(self, async_client: AsyncClient):
        """Test login with an email that does not exist."""
        # Arrange
        non_existent_credentials = {
            "username": "not.found@example.com",
            "password": "any_password",
        }

        # Act
        response = await async_client.post(
            "/api/v1/login/", data=non_existent_credentials
        )

        # Assert
        assert response.status_code == 401
        response_data = response.json()
        assert response_data["error_code"] == errors.INVALID_CREDENTIALS
