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


@pytest.mark.asyncio
async def test_current_returns_latest(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(seeded_field.id), "pii_tags": ["email"]},
        headers=superuser_token_headers,
    )
    r2 = await async_client.post(
        "/api/v1/field-classifications/",
        json={
            "field_id": str(seeded_field.id),
            "pii_tags": ["email", "login"],
        },
        headers=superuser_token_headers,
    )
    second_id = r2.json()["id"]

    r = await async_client.get(
        f"/api/v1/field-classifications/current/{seeded_field.id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == second_id


@pytest.mark.asyncio
async def test_current_404_when_unclassified(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    r = await async_client.get(
        f"/api/v1/field-classifications/current/{seeded_field.id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert r.json()["error_code"] == "FIELD_CLASSIFICATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_by_dataset_current_returns_one_per_classified_field(
    async_client: AsyncClient,
    transactional_session: AsyncSession,
    superuser_token_headers: dict[str, str],
):
    kind = SystemKind(code="KIND_FCAPI_D", name="Kind FCAPI D")
    flavor = SystemFlavor(code="FL_FCAPI_D", name="Flavor FCAPI D", kind=kind)
    system = System(code="SYS_FCAPI_D", name="System FCAPI D", flavor=flavor)
    dataset = DatasetRdbms(
        system=system,
        object_name="customers_fcapi_d",
        schema_name="public",
        table_name="customers",
    )
    email = Field(dataset=dataset, name="email_fcapi_d")
    phone = Field(dataset=dataset, name="phone_fcapi_d")
    transactional_session.add_all([kind, flavor, system, dataset, email, phone])
    await transactional_session.commit()

    await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(email.id), "pii_tags": ["email"]},
        headers=superuser_token_headers,
    )
    r2 = await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(email.id), "pii_tags": ["email", "login"]},
        headers=superuser_token_headers,
    )
    latest_id = r2.json()["id"]

    r = await async_client.get(
        f"/api/v1/field-classifications/by-dataset/{dataset.id}/current",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["id"] == latest_id
    assert body[0]["field_id"] == str(email.id)


@pytest.mark.asyncio
async def test_put_returns_405(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(seeded_field.id), "pii_tags": ["email"]},
        headers=superuser_token_headers,
    )
    obj_id = r.json()["id"]
    r2 = await async_client.put(
        f"/api/v1/field-classifications/{obj_id}",
        json={"pii_tags": ["email_address"]},
        headers=superuser_token_headers,
    )
    assert r2.status_code == 405


@pytest.mark.asyncio
async def test_delete_returns_405(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(seeded_field.id), "pii_tags": ["email"]},
        headers=superuser_token_headers,
    )
    obj_id = r.json()["id"]
    r2 = await async_client.delete(
        f"/api/v1/field-classifications/{obj_id}",
        headers=superuser_token_headers,
    )
    assert r2.status_code == 405
