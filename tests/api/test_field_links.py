from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.main import app
from backend.models import System, SystemFlavor, SystemKind, User


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="field_link_super.user@example.com",
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
async def test_system(transactional_session: AsyncSession) -> System:
    kind = SystemKind(code="KIND_FL_API", name="Kind FL API")
    flavor = SystemFlavor(code="FL_FL_API", name="Flavor FL API", kind=kind)
    system = System(code="SYS_FL_API", name="System FL API", flavor=flavor)
    transactional_session.add_all([kind, flavor, system])
    await transactional_session.commit()
    await transactional_session.refresh(system)
    return system


async def _create_dataset(
    async_client: AsyncClient,
    headers: dict,
    system_id,
    name: str,
    layer: str,
) -> str:
    resp = await async_client.post(
        "/api/v1/datasets/",
        json={
            "system_id": str(system_id),
            "object_name": name,
            "kind": "rdbms",
            "schema_name": "s",
            "table_name": name,
            "layer": layer,
        },
        headers=headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return resp.json()["id"]


async def _create_field(
    async_client: AsyncClient,
    headers: dict,
    dataset_id: str,
    name: str,
    origin: str = "mapped",
) -> str:
    resp = await async_client.post(
        "/api/v1/fields/",
        json={"dataset_id": dataset_id, "name": name, "origin": origin},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
class TestFieldLinkAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_field_link_happy(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        src = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "fl_src", "source"
        )
        tgt = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "fl_tgt", "raw"
        )
        sf = await _create_field(async_client, superuser_token_headers, src, "c")
        tf = await _create_field(async_client, superuser_token_headers, tgt, "c")
        link_resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={"source_dataset_id": src, "target_dataset_id": tgt},
            headers=superuser_token_headers,
        )
        assert link_resp.status_code == status.HTTP_201_CREATED, link_resp.text
        link_id = link_resp.json()["id"]

        resp = await async_client.post(
            f"/api/v1/dataset-links/{link_id}/field-links/",
            json={
                "dataset_link_id": link_id,
                "source_field_id": sf,
                "target_field_id": tf,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

    async def test_create_field_link_wrong_target_dataset(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        src = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "wt_src", "source"
        )
        tgt = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "wt_tgt", "raw"
        )
        other = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "wt_oth", "raw"
        )
        sf = await _create_field(async_client, superuser_token_headers, src, "c")
        tf_wrong = await _create_field(
            async_client, superuser_token_headers, other, "c"
        )
        link_resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={"source_dataset_id": src, "target_dataset_id": tgt},
            headers=superuser_token_headers,
        )
        assert link_resp.status_code == status.HTTP_201_CREATED, link_resp.text
        link_id = link_resp.json()["id"]

        resp = await async_client.post(
            f"/api/v1/dataset-links/{link_id}/field-links/",
            json={
                "dataset_link_id": link_id,
                "source_field_id": sf,
                "target_field_id": tf_wrong,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["error_code"] == "FIELD_LINK_TARGET_DATASET_MISMATCH"

    async def test_bulk_create_field_links(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        src = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "bk_s", "source"
        )
        tgt = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "bk_t", "raw"
        )
        sf1 = await _create_field(async_client, superuser_token_headers, src, "a")
        sf2 = await _create_field(async_client, superuser_token_headers, src, "b")
        tf1 = await _create_field(async_client, superuser_token_headers, tgt, "a")
        tf2 = await _create_field(async_client, superuser_token_headers, tgt, "b")
        link_resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={"source_dataset_id": src, "target_dataset_id": tgt},
            headers=superuser_token_headers,
        )
        assert link_resp.status_code == status.HTTP_201_CREATED, link_resp.text
        link_id = link_resp.json()["id"]

        resp = await async_client.post(
            f"/api/v1/dataset-links/{link_id}/field-links/bulk",
            json=[
                {
                    "dataset_link_id": link_id,
                    "source_field_id": sf1,
                    "target_field_id": tf1,
                },
                {
                    "dataset_link_id": link_id,
                    "source_field_id": sf2,
                    "target_field_id": tf2,
                },
            ],
            headers=superuser_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert len(resp.json()) == 2
