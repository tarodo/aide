import uuid
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.main import app
from backend.models import User


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
        self, async_client: AsyncClient, transactional_session: AsyncSession
    ):
        """
        Test creating a user successfully.
        Verifies:
        - 201 status code
        - Correct JSON response
        - User is persisted in the database
        """
        # Arrange
        user_data = {
            "email": "test.create@example.com",
            "password": "a_secure_password",
            "full_name": "Test Create User",
        }

        # Act
        response = await async_client.post("/api/v1/users/", json=user_data)

        # Assert API response
        assert response.status_code == 201
        response_data = response.json()
        assert response_data["email"] == user_data["email"]
        assert response_data["full_name"] == user_data["full_name"]
        assert "id" in response_data
        user_id = response_data["id"]

        # Assert database state
        db_user = await transactional_session.get(User, uuid.UUID(user_id))
        assert db_user is not None
        assert db_user.email == user_data["email"]
        assert db_user.full_name == user_data["full_name"]
        assert db_user.id == uuid.UUID(user_id)

    async def test_create_user_duplicate_email(self, async_client: AsyncClient):
        """
        Test creating a user with an email that already exists.
        Verifies:
        - 400 status code
        - Correct error detail in response
        """
        # Arrange: create a user first
        user_data = {
            "email": "duplicate.email@example.com",
            "password": "password123",
            "full_name": "First User",
        }
        response = await async_client.post("/api/v1/users/", json=user_data)
        assert response.status_code == 201

        # Act: try to create another user with the same email
        duplicate_user_data = {
            "email": "duplicate.email@example.com",
            "password": "another_password",
            "full_name": "Second User",
        }
        response = await async_client.post("/api/v1/users/", json=duplicate_user_data)

        # Assert
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    async def test_get_user_success(self, async_client: AsyncClient):
        """
        Test getting an existing user by ID.
        Verifies:
        - 200 status code
        - Response matches the created user data
        """
        # Arrange: create a user
        user_data = {
            "email": "get.user@example.com",
            "password": "password123",
            "full_name": "Get User Test",
        }
        create_response = await async_client.post("/api/v1/users/", json=user_data)
        assert create_response.status_code == 201
        created_user = create_response.json()
        user_id = created_user["id"]

        # Act
        get_response = await async_client.get(f"/api/v1/users/{user_id}")

        # Assert
        assert get_response.status_code == 200
        assert get_response.json() == created_user

    async def test_get_user_not_found(self, async_client: AsyncClient):
        """Test getting a user with a non-existent ID."""
        non_existent_uuid = uuid.uuid4()
        response = await async_client.get(f"/api/v1/users/{non_existent_uuid}")
        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"
