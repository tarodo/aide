from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import (
    DatasetRdbms,
    DatasetSchema,
    DataType,
    Field,
    FieldBinding,
    System,
    SystemFlavor,
    SystemKind,
    TypeInstance,
    User,
)


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="fb_super.user@example.com",
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
async def test_dependencies(transactional_session: AsyncSession) -> dict:
    kind = SystemKind(code="RDBMS_FB_TEST", name="RDBMS for FB Test")
    flavor = SystemFlavor(code="PG_FB_TEST", name="Postgres for FB Test", kind=kind)
    system = System(code="PROD_DB_FB_TEST", name="Prod DB for FB Test", flavor=flavor)

    dataset = DatasetRdbms(
        system=system,
        object_name="customers_fb_test",
        schema_name="public",
        table_name="customers",
    )

    schema = DatasetSchema(dataset=dataset, version_num=1, schema={})
    field = Field(dataset=dataset, name="id")
    data_type = DataType(system_flavor=flavor, code="INTEGER_FB", params_schema={})
    transactional_session.add_all(
        [kind, flavor, system, dataset, schema, field, data_type]
    )
    await transactional_session.flush()

    type_instance = TypeInstance(
        data_type_id=data_type.id,
        type_params={"precision": 10},
        parent_id=None,
        slot=None,
    )
    transactional_session.add(type_instance)
    await transactional_session.commit()

    return {
        "field": field,
        "dataset_schema": schema,
        "data_type": data_type,
        "type_instance": type_instance,
    }


@pytest_asyncio.fixture
async def test_field_binding(
    transactional_session: AsyncSession, test_dependencies: dict
) -> FieldBinding:
    binding = FieldBinding(
        field=test_dependencies["field"],
        dataset_schema=test_dependencies["dataset_schema"],
        position=1,
        is_nullable=False,
        type_instance=test_dependencies["type_instance"],
    )
    transactional_session.add(binding)
    await transactional_session.commit()
    return binding


@pytest.mark.asyncio
class TestFieldBindingAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_field_binding_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dependencies: dict,
    ):
        data = {
            "field_id": str(test_dependencies["field"].id),
            "dataset_schema_id": str(test_dependencies["dataset_schema"].id),
            "position": 10,
            "is_nullable": True,
            "type_instance_id": str(test_dependencies["type_instance"].id),
        }
        response = await async_client.post(
            "/api/v1/field-bindings/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["position"] == 10
        assert res_json["type_instance_id"] == str(
            test_dependencies["type_instance"].id
        )

    async def test_create_field_binding_duplicate_field(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field_binding: FieldBinding,
    ):
        data = {
            "field_id": str(test_field_binding.field_id),
            "dataset_schema_id": str(test_field_binding.dataset_schema_id),
            "position": 99,
            "type_instance_id": str(test_field_binding.type_instance_id),
        }
        response = await async_client.post(
            "/api/v1/field-bindings/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert (
            response.json()["error_code"]
            == errors.FIELD_BINDING_FIELD_ID_ALREADY_EXISTS
        )

    async def test_create_field_binding_duplicate_position(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field_binding: FieldBinding,
        test_dependencies: dict,
        transactional_session: AsyncSession,
    ):
        # Create a new field to avoid FK violation on field_id
        new_field = Field(
            dataset_id=test_dependencies["field"].dataset_id, name="email"
        )
        transactional_session.add(new_field)
        await transactional_session.commit()

        data = {
            "field_id": str(new_field.id),
            "dataset_schema_id": str(test_field_binding.dataset_schema_id),
            "position": test_field_binding.position,
            "type_instance_id": str(test_field_binding.type_instance_id),
        }
        response = await async_client.post(
            "/api/v1/field-bindings/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert (
            response.json()["error_code"]
            == errors.FIELD_BINDING_POSITION_ALREADY_EXISTS
        )

    async def test_create_field_binding_type_instance_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dependencies: dict,
    ):
        data = {
            "field_id": str(test_dependencies["field"].id),
            "dataset_schema_id": str(test_dependencies["dataset_schema"].id),
            "position": 1,
            "type_instance_id": "00000000-0000-0000-0000-000000000000",
        }
        response = await async_client.post(
            "/api/v1/field-bindings/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.TYPE_INSTANCE_NOT_FOUND

    async def test_get_field_binding_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field_binding: FieldBinding,
    ):
        response = await async_client.get(
            f"/api/v1/field-bindings/{test_field_binding.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_field_binding.id)

    async def test_get_all_field_bindings_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field_binding: FieldBinding,
    ):
        response = await async_client.get(
            "/api/v1/field-bindings/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_field_binding(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field_binding: FieldBinding,
    ):
        update_data = {"is_nullable": True, "position": 2}
        response = await async_client.put(
            f"/api/v1/field-bindings/{test_field_binding.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["is_nullable"] is True
        assert res_json["position"] == 2

    async def test_delete_field_binding(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field_binding: FieldBinding,
    ):
        response = await async_client.delete(
            f"/api/v1/field-bindings/{test_field_binding.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_field_binding.id)

        # Verify it's gone
        response = await async_client.get(
            f"/api/v1/field-bindings/{test_field_binding.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
