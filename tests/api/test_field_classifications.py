import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.main import app
from backend.models import (
    DatasetRdbms,
    Field,
    System,
    SystemFlavor,
    SystemKind,
    User,
)


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="fc_super.user@example.com",
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


@pytest_asyncio.fixture
async def seeded_field(transactional_session: AsyncSession) -> Field:
    kind = SystemKind(code="KIND_FCAPI", name="Kind FC API")
    flavor = SystemFlavor(code="FL_FCAPI", name="Flavor FC API", kind=kind)
    system = System(code="SYS_FCAPI", name="System FC API", flavor=flavor)
    dataset = DatasetRdbms(
        system=system,
        object_name="customers_fcapi",
        schema_name="public",
        table_name="customers",
    )
    field = Field(dataset=dataset, name="email_api")
    transactional_session.add_all([kind, flavor, system, dataset, field])
    await transactional_session.commit()
    return field


@pytest.mark.asyncio
async def test_create_happy_path(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    payload = {"field_id": str(seeded_field.id), "pii_tags": ["email"]}
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json=payload,
        headers=superuser_token_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["field_id"] == str(seeded_field.id)
    assert body["pii_tags"] == ["email"]


@pytest.mark.asyncio
async def test_create_with_empty_pii_tags_is_valid(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    payload = {"field_id": str(seeded_field.id), "pii_tags": []}
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json=payload,
        headers=superuser_token_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["pii_tags"] == []


@pytest.mark.asyncio
async def test_create_missing_pii_tags_is_422(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    payload = {"field_id": str(seeded_field.id)}
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json=payload,
        headers=superuser_token_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_unknown_field_id_is_404(
    async_client: AsyncClient,
    superuser_token_headers: dict[str, str],
):
    payload = {"field_id": str(uuid.uuid4()), "pii_tags": ["email"]}
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json=payload,
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert r.json()["error_code"] == "FIELD_NOT_FOUND"
