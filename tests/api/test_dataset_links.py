from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import System, SystemFlavor, SystemKind, User


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="dataset_link_super.user@example.com",
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
    kind = SystemKind(code="RDBMS_DLINK_TEST", name="RDBMS for DatasetLink Test")
    flavor = SystemFlavor(
        code="PG_DLINK_TEST", name="Postgres for DatasetLink Test", kind=kind
    )
    system = System(
        code="PROD_DB_DLINK_TEST", name="Prod DB for DatasetLink Test", flavor=flavor
    )
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
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_schema(
    async_client: AsyncClient,
    headers: dict,
    dataset_id: str,
    version: int = 1,
) -> str:
    resp = await async_client.post(
        "/api/v1/dataset-schemas/",
        json={"dataset_id": dataset_id, "version_num": version, "schema": {}},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
class TestDatasetLinkAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_and_get_dataset_link(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        src_id = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "src_l1", "source"
        )
        tgt_id = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "tgt_l1", "raw"
        )
        src_schema_id = await _create_schema(
            async_client, superuser_token_headers, src_id
        )
        tgt_schema_id = await _create_schema(
            async_client, superuser_token_headers, tgt_id
        )

        resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={
                "source_dataset_id": src_id,
                "target_dataset_id": tgt_id,
                "source_schema_id": src_schema_id,
                "target_schema_id": tgt_schema_id,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == 201, resp.text
        link_id = resp.json()["id"]

        resp2 = await async_client.get(
            f"/api/v1/dataset-links/{link_id}", headers=superuser_token_headers
        )
        assert resp2.status_code == 200
        assert resp2.json()["id"] == link_id

    async def test_create_dataset_link_layer_violation(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        src_id = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "src_v", "core"
        )
        tgt_id = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "tgt_v", "raw"
        )
        src_schema_id = await _create_schema(
            async_client, superuser_token_headers, src_id
        )
        tgt_schema_id = await _create_schema(
            async_client, superuser_token_headers, tgt_id
        )

        resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={
                "source_dataset_id": src_id,
                "target_dataset_id": tgt_id,
                "source_schema_id": src_schema_id,
                "target_schema_id": tgt_schema_id,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == errors.DATASET_LINK_LAYER_ORDER

    async def test_create_dataset_link_duplicate(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        s = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "dup_s", "source"
        )
        t = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "dup_t", "raw"
        )
        s_schema_id = await _create_schema(async_client, superuser_token_headers, s)
        t_schema_id = await _create_schema(async_client, superuser_token_headers, t)
        payload = {
            "source_dataset_id": s,
            "target_dataset_id": t,
            "source_schema_id": s_schema_id,
            "target_schema_id": t_schema_id,
        }
        r1 = await async_client.post(
            "/api/v1/dataset-links/", json=payload, headers=superuser_token_headers
        )
        assert r1.status_code == 201
        r2 = await async_client.post(
            "/api/v1/dataset-links/", json=payload, headers=superuser_token_headers
        )
        assert r2.status_code == 409
        assert r2.json()["error_code"] == errors.DATASET_LINK_ALREADY_EXISTS


@pytest.mark.asyncio
class TestDatasetLinkPinAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    async def test_create_requires_schema_ids(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        src_id = await _create_dataset(
            async_client,
            superuser_token_headers,
            test_system.id,
            "pin_src",
            "source",
        )
        tgt_id = await _create_dataset(
            async_client,
            superuser_token_headers,
            test_system.id,
            "pin_tgt",
            "raw",
        )
        resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={"source_dataset_id": src_id, "target_dataset_id": tgt_id},
            headers=superuser_token_headers,
        )
        assert resp.status_code == 422

    async def test_create_with_schema_ids_returns_pins(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        src_id = await _create_dataset(
            async_client,
            superuser_token_headers,
            test_system.id,
            "pin2_src",
            "source",
        )
        tgt_id = await _create_dataset(
            async_client,
            superuser_token_headers,
            test_system.id,
            "pin2_tgt",
            "raw",
        )
        src_schema_id = await _create_schema(
            async_client, superuser_token_headers, src_id
        )
        tgt_schema_id = await _create_schema(
            async_client, superuser_token_headers, tgt_id
        )

        resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={
                "source_dataset_id": src_id,
                "target_dataset_id": tgt_id,
                "source_schema_id": src_schema_id,
                "target_schema_id": tgt_schema_id,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["source_schema_id"] == src_schema_id
        assert body["target_schema_id"] == tgt_schema_id

    async def test_create_schema_dataset_mismatch_returns_422(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        src_id = await _create_dataset(
            async_client,
            superuser_token_headers,
            test_system.id,
            "pin3_src",
            "source",
        )
        tgt_id = await _create_dataset(
            async_client,
            superuser_token_headers,
            test_system.id,
            "pin3_tgt",
            "raw",
        )
        unrelated_id = await _create_dataset(
            async_client,
            superuser_token_headers,
            test_system.id,
            "pin3_unrel",
            "source",
        )
        src_schema_id = await _create_schema(
            async_client, superuser_token_headers, unrelated_id
        )
        tgt_schema_id = await _create_schema(
            async_client, superuser_token_headers, tgt_id
        )

        resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={
                "source_dataset_id": src_id,
                "target_dataset_id": tgt_id,
                "source_schema_id": src_schema_id,
                "target_schema_id": tgt_schema_id,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == errors.SCHEMA_DATASET_MISMATCH

    async def test_compat_endpoint_returns_report(
        self, async_client, superuser_token_headers, test_system
    ):
        src_id = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "cpt_src", "source"
        )
        tgt_id = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "cpt_tgt", "raw"
        )
        ss_id = await _create_schema(async_client, superuser_token_headers, src_id)
        ts_id = await _create_schema(async_client, superuser_token_headers, tgt_id)
        resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={
                "source_dataset_id": src_id,
                "target_dataset_id": tgt_id,
                "source_schema_id": ss_id,
                "target_schema_id": ts_id,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == 201
        link_id = resp.json()["id"]

        resp = await async_client.get(
            f"/api/v1/dataset-links/{link_id}/compat",
            headers=superuser_token_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["dataset_link_id"] == link_id
        assert body["summary"]["total"] == 0
        assert body["status"] == "ok"

    async def test_list_compat_endpoint(
        self, async_client, superuser_token_headers, test_system
    ):
        resp = await async_client.get(
            "/api/v1/dataset-links/compat",
            headers=superuser_token_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "items" in body
        assert "total" in body
