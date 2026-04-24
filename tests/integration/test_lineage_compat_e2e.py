"""End-to-end scenarios covering the lineage data-contract flow."""

from __future__ import annotations

from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.main import app
from backend.models import System, SystemFlavor, SystemKind, User


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="integ_lineage.super@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
        is_superuser=True,
    )
    transactional_session.add(user)
    await transactional_session.commit()
    return user


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def headers(async_client: AsyncClient, superuser: User) -> dict[str, str]:
    r = await async_client.post(
        "/api/v1/login/",
        data={"username": superuser.email, "password": "password123"},
    )
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def system(transactional_session: AsyncSession) -> System:
    kind = SystemKind(code="INT_LIN_K", name="Integ Lineage Kind")
    flavor = SystemFlavor(code="INT_LIN_F", name="Integ Lineage Flavor", kind=kind)
    system = System(code="INT_LIN_S", name="Integ Lineage System", flavor=flavor)
    transactional_session.add_all([kind, flavor, system])
    await transactional_session.commit()
    await transactional_session.refresh(system)
    return system


@pytest.mark.asyncio
async def test_drift_detection_and_repin_e2e(
    async_client: AsyncClient, headers: dict, system, transactional_session
):
    async def _mk_ds(name: str, layer: str) -> str:
        r = await async_client.post(
            "/api/v1/datasets/",
            json={
                "system_id": str(system.id),
                "object_name": name,
                "kind": "rdbms",
                "schema_name": "s",
                "table_name": name,
                "layer": layer,
            },
            headers=headers,
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    src_id = await _mk_ds("e2e_src", "source")
    tgt_id = await _mk_ds("e2e_tgt", "raw")

    async def _mk_schema(dataset_id: str, v: int) -> str:
        r = await async_client.post(
            "/api/v1/dataset-schemas/",
            json={"dataset_id": dataset_id, "version_num": v, "schema": {}},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    s1 = await _mk_schema(src_id, 1)
    t1 = await _mk_schema(tgt_id, 1)

    # Create link pinned to v1/v1
    r = await async_client.post(
        "/api/v1/dataset-links/",
        json={
            "source_dataset_id": src_id,
            "target_dataset_id": tgt_id,
            "source_schema_id": s1,
            "target_schema_id": t1,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    link_id = r.json()["id"]
    link_row_version = r.json()["row_version"]

    # Compat at v1/v1 — ok, no drift
    r = await async_client.get(
        f"/api/v1/dataset-links/{link_id}/compat", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["pin_drift"]["source"]["has_drift"] is False

    # New source schema v2 → drift
    s2 = await _mk_schema(src_id, 2)
    r = await async_client.get(
        f"/api/v1/dataset-links/{link_id}/compat", headers=headers
    )
    body = r.json()
    assert body["pin_drift"]["source"]["has_drift"] is True
    assert body["pin_drift"]["source"]["latest_version"] == 2
    assert body["status"] == "warn"

    # Re-pin to source v2
    r = await async_client.patch(
        f"/api/v1/dataset-links/{link_id}",
        json={"source_schema_id": s2, "row_version": link_row_version},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # Drift cleared
    r = await async_client.get(
        f"/api/v1/dataset-links/{link_id}/compat", headers=headers
    )
    body = r.json()
    assert body["pin_drift"]["source"]["has_drift"] is False
    assert body["status"] == "ok"
