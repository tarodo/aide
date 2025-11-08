import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from backend.main import app


def test_root(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}


@pytest.mark.asyncio
async def test_create_and_get_user():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # Create user
        create_response = await ac.post(
            "/api/v1/users/",
            json={
                "email": "test@example.com",
                "password": "password",
                "full_name": "Test User",
            },
        )
        assert create_response.status_code == 201
        user_data = create_response.json()
        assert user_data["email"] == "test@example.com"
        assert user_data["full_name"] == "Test User"
        user_id = user_data["id"]

        # Get user
        get_response = await ac.get(f"/api/v1/users/{user_id}")
        assert get_response.status_code == 200
        get_user_data = get_response.json()
        assert get_user_data == user_data

        # Try to create same user again, should fail
        create_again_response = await ac.post(
            "/api/v1/users/",
            json={
                "email": "test@example.com",
                "password": "password",
                "full_name": "Test User",
            },
        )
        assert create_again_response.status_code == 400
