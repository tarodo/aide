"""Integration tests for batch-create endpoints.

Covers:
  POST /api/v1/fields/batch
  POST /api/v1/type-instances/batch
  POST /api/v1/field-bindings/batch
  POST /api/v1/data-types/batch
"""

from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.core.settings import settings
from backend.main import app
from backend.models import (
    Dataset,
    DatasetRdbms,
    Field,
    System,
    SystemFlavor,
    SystemKind,
    User,
)

# ---------------------------------------------------------------------------
# Fixtures (unique codes/emails to avoid collision with other test files)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="batch_super.user@example.com",
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
    kind = SystemKind(code="RDBMS_BATCH_TEST", name="RDBMS for Batch Test")
    flavor = SystemFlavor(
        code="PG_BATCH_TEST", name="Postgres for Batch Test", kind=kind
    )
    system = System(
        code="PROD_DB_BATCH_TEST", name="Prod DB for Batch Test", flavor=flavor
    )
    transactional_session.add_all([kind, flavor, system])
    await transactional_session.commit()
    await transactional_session.refresh(system)
    return system


@pytest_asyncio.fixture
async def test_dataset(
    transactional_session: AsyncSession, test_system: System
) -> Dataset:
    dataset = DatasetRdbms(
        system=test_system,
        object_name="customers_table_batch_test",
        schema_name="public",
        table_name="customers",
    )
    transactional_session.add(dataset)
    await transactional_session.commit()
    await transactional_session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBatchEndpoints:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    # ------------------------------------------------------------------
    # Fields batch — deep coverage
    # ------------------------------------------------------------------

    async def test_fields_batch_create_ok(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        superuser: User,
        test_dataset: Dataset,
        transactional_session: AsyncSession,
    ):
        """3 fields for one dataset → 201, envelope shape correct, DB has 3 rows."""
        payload = {
            "items": [
                {"dataset_id": str(test_dataset.id), "name": "col_a"},
                {"dataset_id": str(test_dataset.id), "name": "col_b"},
                {"dataset_id": str(test_dataset.id), "name": "col_c"},
            ]
        }
        response = await async_client.post(
            "/api/v1/fields/batch",
            json=payload,
            headers=superuser_token_headers,
        )
        assert response.status_code == 201

        body = response.json()
        assert body["count"] == 3
        assert len(body["items"]) == 3

        # Names come back in insertion order
        returned_names = [item["name"] for item in body["items"]]
        assert returned_names == ["col_a", "col_b", "col_c"]

        # created_by is populated from the JWT user
        for item in body["items"]:
            assert item["created_by"] == str(superuser.id)

        # DB has exactly 3 rows for this dataset
        result = await transactional_session.execute(
            select(Field).where(Field.dataset_id == test_dataset.id)
        )
        db_fields = result.scalars().all()
        assert len(db_fields) == 3

    async def test_fields_batch_all_or_nothing(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset: Dataset,
        transactional_session: AsyncSession,
    ):
        """Two items with the same new name in one batch: both pass _pre_create
        (DB empty), both get added via add_all, flush() raises
        UniqueViolationError, UoW.__aexit__ rolls back. Proves DB-level
        transactional rollback (not just the app-level _pre_create short-circuit).
        """
        from sqlalchemy.exc import IntegrityError

        payload = {
            "items": [
                {"dataset_id": str(test_dataset.id), "name": "same_name"},
                {"dataset_id": str(test_dataset.id), "name": "same_name"},
            ]
        }
        with pytest.raises(IntegrityError):
            await async_client.post(
                "/api/v1/fields/batch",
                json=payload,
                headers=superuser_token_headers,
            )

        # Rollback proven: zero rows with same_name despite the first item
        # having been added to the session before flush failed.
        result = await transactional_session.execute(
            select(Field).where(
                Field.dataset_id == test_dataset.id,
                Field.name == "same_name",
            )
        )
        assert result.scalars().all() == []

    async def test_fields_batch_too_large(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset: Dataset,
        monkeypatch,
    ):
        """MAX_BATCH_SIZE=2, 3 items → 422."""
        monkeypatch.setattr(settings, "MAX_BATCH_SIZE", 2)

        payload = {
            "items": [
                {"dataset_id": str(test_dataset.id), "name": "x1"},
                {"dataset_id": str(test_dataset.id), "name": "x2"},
                {"dataset_id": str(test_dataset.id), "name": "x3"},
            ]
        }
        response = await async_client.post(
            "/api/v1/fields/batch",
            json=payload,
            headers=superuser_token_headers,
        )
        assert response.status_code == 422

    async def test_fields_batch_empty_rejected(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        """Empty items list → 422 (BatchCreateRequest min_length=1 validation)."""
        response = await async_client.post(
            "/api/v1/fields/batch",
            json={"items": []},
            headers=superuser_token_headers,
        )
        assert response.status_code == 422

    # ------------------------------------------------------------------
    # Smoke tests — endpoint registration for the other 3 resources
    # ------------------------------------------------------------------

    async def test_field_bindings_batch_endpoint_registered(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        """Empty payload → 422 proves the route is registered and validation runs."""
        response = await async_client.post(
            "/api/v1/field-bindings/batch",
            json={"items": []},
            headers=superuser_token_headers,
        )
        assert response.status_code == 422

    async def test_type_instances_batch_endpoint_registered(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        """Empty payload → 422 proves the route is registered and validation runs."""
        response = await async_client.post(
            "/api/v1/type-instances/batch",
            json={"items": []},
            headers=superuser_token_headers,
        )
        assert response.status_code == 422

    async def test_data_types_batch_endpoint_registered(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        """Empty payload → 422 proves the route is registered and validation runs."""
        response = await async_client.post(
            "/api/v1/data-types/batch",
            json={"items": []},
            headers=superuser_token_headers,
        )
        assert response.status_code == 422
