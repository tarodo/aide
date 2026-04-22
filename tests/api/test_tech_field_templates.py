from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.main import app
from backend.models import User


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="tech_field_tpl_super.user@example.com",
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


@pytest.mark.asyncio
class TestTechFieldTemplateAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_template(
        self, async_client: AsyncClient, superuser_token_headers: dict
    ):
        resp = await async_client.post(
            "/api/v1/tech-field-templates/",
            json={"code": "scd2_v1", "name": "SCD2 v1", "layer": "core"},
            headers=superuser_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()["code"] == "scd2_v1"

    async def test_create_duplicate_code(
        self, async_client: AsyncClient, superuser_token_headers: dict
    ):
        payload = {"code": "dup_v1", "name": "Dup", "layer": "core"}
        r1 = await async_client.post(
            "/api/v1/tech-field-templates/",
            json=payload,
            headers=superuser_token_headers,
        )
        assert r1.status_code == status.HTTP_201_CREATED
        r2 = await async_client.post(
            "/api/v1/tech-field-templates/",
            json=payload,
            headers=superuser_token_headers,
        )
        assert r2.status_code == status.HTTP_409_CONFLICT
        assert r2.json()["error_code"] == "TECH_FIELD_TEMPLATE_ALREADY_EXISTS"

    async def test_add_field_to_template(
        self, async_client: AsyncClient, superuser_token_headers: dict
    ):
        tpl = (
            await async_client.post(
                "/api/v1/tech-field-templates/",
                json={"code": "add_fld_v1", "name": "Addf", "layer": "core"},
                headers=superuser_token_headers,
            )
        ).json()
        resp = await async_client.post(
            f"/api/v1/tech-field-templates/{tpl['id']}/fields",
            json={
                "template_id": tpl["id"],
                "name": "valid_from",
                "type_code": "TIMESTAMP",
                "order": 0,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()["name"] == "valid_from"
