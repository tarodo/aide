import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import CastRule, DataType, SystemFlavor, SystemKind, User


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    """Fixture for a superuser persisted in the database."""
    user = User(
        email="cr_super.user@example.com",
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
    """Fixture for authentication headers for a superuser."""
    login_data = {"username": superuser.email, "password": "password123"}
    r = await async_client.post("/api/v1/login/", data=login_data)
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_system_flavor(transactional_session: AsyncSession) -> SystemFlavor:
    kind = SystemKind(code="RDBMS_CR_TEST", name="RDBMS for Cast Rule Test")
    flavor = SystemFlavor(code="PG_CR_TEST", name="Postgres for CR Test", kind=kind)
    transactional_session.add_all([kind, flavor])
    await transactional_session.commit()
    await transactional_session.refresh(flavor)
    return flavor


@pytest_asyncio.fixture
async def test_data_type1(
    transactional_session: AsyncSession, test_system_flavor: SystemFlavor
) -> DataType:
    dt = DataType(
        system_flavor=test_system_flavor,
        code="INTEGER_CR",
        params_schema={},
    )
    transactional_session.add(dt)
    await transactional_session.commit()
    await transactional_session.refresh(dt)
    return dt


@pytest_asyncio.fixture
async def test_data_type2(
    transactional_session: AsyncSession, test_system_flavor: SystemFlavor
) -> DataType:
    dt = DataType(
        system_flavor=test_system_flavor,
        code="BIGINT_CR",
        params_schema={},
    )
    transactional_session.add(dt)
    await transactional_session.commit()
    await transactional_session.refresh(dt)
    return dt


@pytest_asyncio.fixture
async def test_cast_rule(
    transactional_session: AsyncSession,
    test_data_type1: DataType,
    test_data_type2: DataType,
) -> CastRule:
    cr = CastRule(
        source_data_type=test_data_type1,
        target_data_type=test_data_type2,
        param_mapping={},
        safety="safe",
    )
    transactional_session.add(cr)
    await transactional_session.commit()
    await transactional_session.refresh(cr)
    return cr


@pytest.mark.asyncio
class TestCastRuleAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        """Async client for making API requests."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_cast_rule_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_type1: DataType,
        test_data_type2: DataType,
    ):
        data = {
            "source_data_type_id": str(test_data_type2.id),
            "target_data_type_id": str(test_data_type1.id),
            "param_mapping": {"some_param": "some_value"},
            "safety": "implicit",
        }
        response = await async_client.post(
            "/api/v1/cast-rules/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["safety"] == "implicit"
        assert res_json["source_data_type_id"] == str(test_data_type2.id)

    async def test_create_cast_rule_duplicate(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_cast_rule: CastRule,
    ):
        data = {
            "source_data_type_id": str(test_cast_rule.source_data_type_id),
            "target_data_type_id": str(test_cast_rule.target_data_type_id),
            "param_mapping": {},
            "safety": "safe",
        }
        response = await async_client.post(
            "/api/v1/cast-rules/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.CAST_RULE_ALREADY_EXISTS

    async def test_create_cast_rule_data_type_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_type1: DataType,
    ):
        data = {
            "source_data_type_id": str(test_data_type1.id),
            "target_data_type_id": str(uuid.uuid4()),
            "param_mapping": {},
            "safety": "safe",
        }
        response = await async_client.post(
            "/api/v1/cast-rules/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.DATA_TYPE_NOT_FOUND

    async def test_get_cast_rule_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_cast_rule: CastRule,
    ):
        response = await async_client.get(
            f"/api/v1/cast-rules/{test_cast_rule.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_cast_rule.id)

    async def test_get_all_cast_rules_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_cast_rule: CastRule,
    ):
        response = await async_client.get(
            "/api/v1/cast-rules/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_cast_rule(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_cast_rule: CastRule,
    ):
        update_data = {"safety": "unsafe"}
        response = await async_client.put(
            f"/api/v1/cast-rules/{test_cast_rule.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["safety"] == "unsafe"

    async def test_delete_cast_rule(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_cast_rule: CastRule,
    ):
        response = await async_client.delete(
            f"/api/v1/cast-rules/{test_cast_rule.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_cast_rule.id)

        # Verify it's gone
        response = await async_client.get(
            f"/api/v1/cast-rules/{test_cast_rule.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
