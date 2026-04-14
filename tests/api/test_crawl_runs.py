# tests/api/test_crawl_runs.py
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import (
    CrawlRun,
    System,
    SystemFlavor,
    SystemKind,
    User,
)


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="crawl_super@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
        is_superuser=True,
    )
    transactional_session.add(user)
    await transactional_session.commit()
    await transactional_session.refresh(user)
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
    kind = SystemKind(code="RDBMS_CRAWL_TEST", name="RDBMS for Crawl Test")
    flavor = SystemFlavor(
        code="PG_CRAWL_TEST", name="Postgres for Crawl Test", kind=kind
    )
    system = System(code="pg-crawl-test", name="PG Crawl Test", flavor=flavor)
    transactional_session.add_all([kind, flavor, system])
    await transactional_session.commit()
    await transactional_session.refresh(system)
    return system


@pytest_asyncio.fixture
async def test_crawl_run(
    transactional_session: AsyncSession, test_system: System
) -> CrawlRun:
    cr = CrawlRun(
        system_id=test_system.id,
        status="running",
        started_at=datetime.now(timezone.utc),
        config={"schemas": ["public"]},
    )
    transactional_session.add(cr)
    await transactional_session.commit()
    await transactional_session.refresh(cr)
    return cr


@pytest.mark.asyncio
class TestCrawlRunAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_crawl_run_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        data = {
            "system_id": str(test_system.id),
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "config": {"schemas": ["public", "analytics"]},
        }
        response = await async_client.post(
            "/api/v1/crawl-runs/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["status"] == "running"
        assert res_json["system_id"] == str(test_system.id)
        assert res_json["config"] == {"schemas": ["public", "analytics"]}

    async def test_create_crawl_run_system_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        data = {
            "system_id": str(uuid.uuid4()),
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "config": {},
        }
        response = await async_client.post(
            "/api/v1/crawl-runs/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.SYSTEM_NOT_FOUND

    async def test_get_crawl_run_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_crawl_run: CrawlRun,
    ):
        response = await async_client.get(
            f"/api/v1/crawl-runs/{test_crawl_run.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_crawl_run.id)

    async def test_get_all_crawl_runs_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_crawl_run: CrawlRun,
    ):
        response = await async_client.get(
            "/api/v1/crawl-runs/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_crawl_run_status(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_crawl_run: CrawlRun,
    ):
        update_data = {
            "status": "completed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "new_datasets": 5,
                "removed_datasets": 0,
                "new_fields": 23,
                "type_changes": 0,
            },
            "row_version": 1,
        }
        response = await async_client.put(
            f"/api/v1/crawl-runs/{test_crawl_run.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "completed"
        assert res_json["summary"]["new_datasets"] == 5

    async def test_filter_crawl_runs_by_system_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_crawl_run: CrawlRun,
        test_system: System,
    ):
        response = await async_client.get(
            f"/api/v1/crawl-runs/?system_id={test_system.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["system_id"] == str(test_system.id)

    async def test_update_crawl_run_with_diff_payload(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_crawl_run: CrawlRun,
    ):
        diff_payload = {
            "schema_version": 1,
            "new_datasets_applied": [],
            "existing_datasets_diff": [],
            "removed_datasets": [],
        }
        update_data = {
            "status": "completed",
            "diff_payload": diff_payload,
            "row_version": 1,
        }
        response = await async_client.put(
            f"/api/v1/crawl-runs/{test_crawl_run.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["diff_payload"]["schema_version"] == 1

        # Verify GET returns the same diff_payload
        get_response = await async_client.get(
            f"/api/v1/crawl-runs/{test_crawl_run.id}",
            headers=superuser_token_headers,
        )
        assert get_response.status_code == 200
        assert get_response.json()["diff_payload"]["schema_version"] == 1
