from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import (
    DataType,
    SystemFlavor,
    SystemKind,
    TypeInstance,
    User,
)


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="ti_super.user@example.com",
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
async def test_data_types(transactional_session: AsyncSession) -> dict:
    """Create system kind, flavor, and several data types for testing."""
    kind = SystemKind(code="RDBMS_TI_TEST", name="RDBMS for TI Test")
    flavor = SystemFlavor(code="PG_TI_TEST", name="Postgres for TI Test", kind=kind)
    varchar_type = DataType(
        system_flavor=flavor, code="VARCHAR", params_schema={"length": "integer"}
    )
    array_type = DataType(system_flavor=flavor, code="ARRAY", params_schema={})
    struct_type = DataType(system_flavor=flavor, code="STRUCT", params_schema={})
    string_type = DataType(system_flavor=flavor, code="STRING", params_schema={})
    int_type = DataType(system_flavor=flavor, code="INT", params_schema={})
    map_type = DataType(system_flavor=flavor, code="MAP", params_schema={})
    decimal_type = DataType(
        system_flavor=flavor,
        code="DECIMAL",
        params_schema={"p": "integer", "s": "integer"},
    )
    transactional_session.add_all(
        [
            kind,
            flavor,
            varchar_type,
            array_type,
            struct_type,
            string_type,
            int_type,
            map_type,
            decimal_type,
        ]
    )
    await transactional_session.commit()
    return {
        "varchar": varchar_type,
        "array": array_type,
        "struct": struct_type,
        "string": string_type,
        "int": int_type,
        "map": map_type,
        "decimal": decimal_type,
    }


@pytest_asyncio.fixture
async def flat_type_instance(
    transactional_session: AsyncSession, test_data_types: dict
) -> TypeInstance:
    """A flat VARCHAR(255) type instance."""
    ti = TypeInstance(
        data_type_id=test_data_types["varchar"].id,
        type_params={"length": 255},
        parent_id=None,
        slot=None,
    )
    transactional_session.add(ti)
    await transactional_session.commit()
    return ti


@pytest_asyncio.fixture
async def array_tree(
    transactional_session: AsyncSession, test_data_types: dict
) -> dict:
    """ARRAY<VARCHAR(255)> — two nodes."""
    root = TypeInstance(
        data_type_id=test_data_types["array"].id,
        type_params=None,
        parent_id=None,
        slot=None,
    )
    transactional_session.add(root)
    await transactional_session.flush()

    element = TypeInstance(
        data_type_id=test_data_types["varchar"].id,
        type_params={"length": 255},
        parent_id=root.id,
        slot="element",
    )
    transactional_session.add(element)
    await transactional_session.commit()
    return {"root": root, "element": element}


@pytest.mark.asyncio
class TestTypeInstanceAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    # ---- Create ----

    async def test_create_flat_type_instance(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_types: dict,
    ):
        data = {
            "data_type_id": str(test_data_types["varchar"].id),
            "type_params": {"length": 255},
        }
        response = await async_client.post(
            "/api/v1/type-instances/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res = response.json()
        assert res["data_type_id"] == str(test_data_types["varchar"].id)
        assert res["type_params"] == {"length": 255}
        assert res["parent_id"] is None
        assert res["slot"] is None

    async def test_create_tree_array_varchar(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_types: dict,
    ):
        # Create root ARRAY
        root_data = {"data_type_id": str(test_data_types["array"].id)}
        response = await async_client.post(
            "/api/v1/type-instances/", json=root_data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        root_id = response.json()["id"]

        # Create child element VARCHAR(255)
        child_data = {
            "data_type_id": str(test_data_types["varchar"].id),
            "type_params": {"length": 255},
            "parent_id": root_id,
            "slot": "element",
        }
        response = await async_client.post(
            "/api/v1/type-instances/", json=child_data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res = response.json()
        assert res["parent_id"] == root_id
        assert res["slot"] == "element"

    async def test_create_deep_tree_array_struct(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_types: dict,
    ):
        """ARRAY<STRUCT<name STRING, age INT>> — 4 nodes."""
        headers = superuser_token_headers

        # Root: ARRAY
        r = await async_client.post(
            "/api/v1/type-instances/",
            json={"data_type_id": str(test_data_types["array"].id)},
            headers=headers,
        )
        assert r.status_code == 201
        array_id = r.json()["id"]

        # STRUCT as element of ARRAY
        r = await async_client.post(
            "/api/v1/type-instances/",
            json={
                "data_type_id": str(test_data_types["struct"].id),
                "parent_id": array_id,
                "slot": "element",
            },
            headers=headers,
        )
        assert r.status_code == 201
        struct_id = r.json()["id"]

        # STRING as field:name of STRUCT
        r = await async_client.post(
            "/api/v1/type-instances/",
            json={
                "data_type_id": str(test_data_types["string"].id),
                "parent_id": struct_id,
                "slot": "field:name",
            },
            headers=headers,
        )
        assert r.status_code == 201

        # INT as field:age of STRUCT
        r = await async_client.post(
            "/api/v1/type-instances/",
            json={
                "data_type_id": str(test_data_types["int"].id),
                "parent_id": struct_id,
                "slot": "field:age",
            },
            headers=headers,
        )
        assert r.status_code == 201

    async def test_create_map_tree(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_types: dict,
    ):
        """MAP<STRING, DECIMAL(10,2)> — three nodes."""
        headers = superuser_token_headers

        r = await async_client.post(
            "/api/v1/type-instances/",
            json={"data_type_id": str(test_data_types["map"].id)},
            headers=headers,
        )
        assert r.status_code == 201
        map_id = r.json()["id"]

        r = await async_client.post(
            "/api/v1/type-instances/",
            json={
                "data_type_id": str(test_data_types["string"].id),
                "parent_id": map_id,
                "slot": "key",
            },
            headers=headers,
        )
        assert r.status_code == 201

        r = await async_client.post(
            "/api/v1/type-instances/",
            json={
                "data_type_id": str(test_data_types["decimal"].id),
                "type_params": {"p": 10, "s": 2},
                "parent_id": map_id,
                "slot": "value",
            },
            headers=headers,
        )
        assert r.status_code == 201

    # ---- Validation ----

    async def test_slot_required_when_parent_set(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_types: dict,
        flat_type_instance: TypeInstance,
    ):
        data = {
            "data_type_id": str(test_data_types["varchar"].id),
            "parent_id": str(flat_type_instance.id),
            # slot is missing
        }
        response = await async_client.post(
            "/api/v1/type-instances/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.TYPE_INSTANCE_SLOT_REQUIRED

    async def test_slot_forbidden_when_root(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_types: dict,
    ):
        data = {
            "data_type_id": str(test_data_types["varchar"].id),
            "slot": "element",  # slot without parent
        }
        response = await async_client.post(
            "/api/v1/type-instances/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.TYPE_INSTANCE_SLOT_FORBIDDEN

    async def test_duplicate_parent_slot_rejected(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_types: dict,
        array_tree: dict,
    ):
        data = {
            "data_type_id": str(test_data_types["string"].id),
            "parent_id": str(array_tree["root"].id),
            "slot": "element",  # already exists
        }
        response = await async_client.post(
            "/api/v1/type-instances/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.TYPE_INSTANCE_SLOT_ALREADY_EXISTS

    async def test_data_type_must_exist(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        data = {
            "data_type_id": "00000000-0000-0000-0000-000000000000",
        }
        response = await async_client.post(
            "/api/v1/type-instances/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.DATA_TYPE_NOT_FOUND

    async def test_parent_must_exist(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_types: dict,
    ):
        data = {
            "data_type_id": str(test_data_types["varchar"].id),
            "parent_id": "00000000-0000-0000-0000-000000000000",
            "slot": "element",
        }
        response = await async_client.post(
            "/api/v1/type-instances/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.TYPE_INSTANCE_PARENT_NOT_FOUND

    # ---- Read ----

    async def test_get_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        flat_type_instance: TypeInstance,
    ):
        response = await async_client.get(
            f"/api/v1/type-instances/{flat_type_instance.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(flat_type_instance.id)

    async def test_get_all_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        flat_type_instance: TypeInstance,
    ):
        response = await async_client.get(
            "/api/v1/type-instances/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_get_tree(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        array_tree: dict,
    ):
        response = await async_client.get(
            f"/api/v1/type-instances/{array_tree['root'].id}/tree",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        tree = response.json()
        assert tree["id"] == str(array_tree["root"].id)
        assert len(tree["children"]) == 1
        child = tree["children"][0]
        assert child["slot"] == "element"
        assert child["type_params"] == {"length": 255}
        assert child["children"] == []

    async def test_get_tree_deep(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_data_types: dict,
    ):
        """Build ARRAY<STRUCT<name STRING, age INT>> and verify tree."""
        headers = superuser_token_headers

        r = await async_client.post(
            "/api/v1/type-instances/",
            json={"data_type_id": str(test_data_types["array"].id)},
            headers=headers,
        )
        array_id = r.json()["id"]

        r = await async_client.post(
            "/api/v1/type-instances/",
            json={
                "data_type_id": str(test_data_types["struct"].id),
                "parent_id": array_id,
                "slot": "element",
            },
            headers=headers,
        )
        struct_id = r.json()["id"]

        await async_client.post(
            "/api/v1/type-instances/",
            json={
                "data_type_id": str(test_data_types["string"].id),
                "parent_id": struct_id,
                "slot": "field:name",
            },
            headers=headers,
        )
        await async_client.post(
            "/api/v1/type-instances/",
            json={
                "data_type_id": str(test_data_types["int"].id),
                "parent_id": struct_id,
                "slot": "field:age",
            },
            headers=headers,
        )

        response = await async_client.get(
            f"/api/v1/type-instances/{array_id}/tree",
            headers=headers,
        )
        assert response.status_code == 200
        tree = response.json()
        assert len(tree["children"]) == 1
        struct_node = tree["children"][0]
        assert struct_node["slot"] == "element"
        assert len(struct_node["children"]) == 2
        slots = {c["slot"] for c in struct_node["children"]}
        assert slots == {"field:name", "field:age"}

    async def test_get_tree_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/type-instances/00000000-0000-0000-0000-000000000000/tree",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.TYPE_INSTANCE_NOT_FOUND

    # ---- Update ----

    async def test_update_type_instance(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        flat_type_instance: TypeInstance,
    ):
        update_data = {"type_params": {"length": 100}}
        response = await async_client.put(
            f"/api/v1/type-instances/{flat_type_instance.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["type_params"] == {"length": 100}

    # ---- Delete ----

    async def test_delete_flat_type_instance(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        flat_type_instance: TypeInstance,
    ):
        response = await async_client.delete(
            f"/api/v1/type-instances/{flat_type_instance.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(flat_type_instance.id)

        # Verify it's gone
        response = await async_client.get(
            f"/api/v1/type-instances/{flat_type_instance.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404

    async def test_delete_root_cascades_to_children(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        array_tree: dict,
    ):
        root_id = str(array_tree["root"].id)
        element_id = str(array_tree["element"].id)

        # Delete root
        response = await async_client.delete(
            f"/api/v1/type-instances/{root_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200

        # Verify root is gone
        response = await async_client.get(
            f"/api/v1/type-instances/{root_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404

        # Verify child is also gone (CASCADE)
        response = await async_client.get(
            f"/api/v1/type-instances/{element_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
