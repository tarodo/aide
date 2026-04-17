import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
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


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="field_super.user@example.com",
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
    kind = SystemKind(code="RDBMS_FIELD_TEST", name="RDBMS for Field Test")
    flavor = SystemFlavor(
        code="PG_FIELD_TEST", name="Postgres for Field Test", kind=kind
    )
    system = System(
        code="PROD_DB_FIELD_TEST", name="Prod DB for Field Test", flavor=flavor
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
        object_name="customers_table_field_test",
        schema_name="public",
        table_name="customers",
    )
    transactional_session.add(dataset)
    await transactional_session.commit()
    await transactional_session.refresh(dataset)
    return dataset


@pytest_asyncio.fixture
async def second_dataset(
    transactional_session: AsyncSession, test_system: System
) -> Dataset:
    """A second dataset for cross-dataset validation tests."""
    dataset = DatasetRdbms(
        system=test_system,
        object_name="orders_table_field_test",
        schema_name="public",
        table_name="orders",
    )
    transactional_session.add(dataset)
    await transactional_session.commit()
    await transactional_session.refresh(dataset)
    return dataset


@pytest_asyncio.fixture
async def test_field(
    transactional_session: AsyncSession,
    test_dataset: Dataset,
) -> Field:
    field = Field(
        dataset=test_dataset,
        name="id",
    )
    transactional_session.add(field)
    await transactional_session.commit()
    await transactional_session.refresh(field)
    return field


@pytest_asyncio.fixture
async def nested_fields(
    transactional_session: AsyncSession,
    test_dataset: Dataset,
) -> dict:
    """Create a nested field structure:
    customer (root)
      ├── name
      └── email
    """
    parent = Field(dataset=test_dataset, name="customer")
    transactional_session.add(parent)
    await transactional_session.flush()

    child_name = Field(dataset=test_dataset, name="name", parent_id=parent.id)
    child_email = Field(
        dataset=test_dataset,
        name="email",
        parent_id=parent.id,
    )
    transactional_session.add_all([child_name, child_email])
    await transactional_session.commit()
    await transactional_session.refresh(parent)
    await transactional_session.refresh(child_name)
    await transactional_session.refresh(child_email)
    return {"parent": parent, "child_name": child_name, "child_email": child_email}


@pytest.mark.asyncio
class TestFieldAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    # ---- Backward Compatibility (root fields) ----

    async def test_create_field_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset: Dataset,
    ):
        data = {
            "dataset_id": str(test_dataset.id),
            "name": "email",
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["name"] == "email"
        assert res_json["parent_id"] is None

    async def test_create_field_duplicate(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        data = {
            "dataset_id": str(test_field.dataset_id),
            "name": test_field.name,
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.FIELD_ALREADY_EXISTS

    async def test_create_field_dataset_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        data = {
            "dataset_id": str(uuid.uuid4()),
            "name": "some_field",
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.DATASET_NOT_FOUND

    async def test_get_field_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        response = await async_client.get(
            f"/api/v1/fields/{test_field.id}", headers=superuser_token_headers
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_field.id)

    async def test_get_all_fields_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        response = await async_client.get(
            "/api/v1/fields/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_field(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        update_data = {"path": "customer.id", "row_version": 1}
        response = await async_client.put(
            f"/api/v1/fields/{test_field.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["path"] == "customer.id"

    async def test_delete_field(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        response = await async_client.delete(
            f"/api/v1/fields/{test_field.id}", headers=superuser_token_headers
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_field.id)

        # Verify it's gone
        response = await async_client.get(
            f"/api/v1/fields/{test_field.id}", headers=superuser_token_headers
        )
        assert response.status_code == 404

    # ---- Nested Field Creation ----

    async def test_create_child_field(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
    ):
        """Create a child field with valid parent_id."""
        data = {
            "dataset_id": str(test_field.dataset_id),
            "parent_id": str(test_field.id),
            "name": "sub_field",
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res = response.json()
        assert res["parent_id"] == str(test_field.id)
        assert res["name"] == "sub_field"

    async def test_create_grandchild_field(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        nested_fields: dict,
    ):
        """Create a grandchild — two levels of nesting."""
        parent = nested_fields["child_name"]
        data = {
            "dataset_id": str(parent.dataset_id),
            "parent_id": str(parent.id),
            "name": "first_name",
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res = response.json()
        assert res["parent_id"] == str(parent.id)

    async def test_same_name_different_parents(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        nested_fields: dict,
        test_dataset: Dataset,
    ):
        """Same name is allowed under different parents."""
        headers = superuser_token_headers
        dataset_id = str(test_dataset.id)

        # Create another root field
        r = await async_client.post(
            "/api/v1/fields/",
            json={"dataset_id": dataset_id, "name": "address"},
            headers=headers,
        )
        assert r.status_code == 201
        address_id = r.json()["id"]

        # Create "name" under customer (already exists via nested_fields)
        # Create "name" under address — should succeed
        r = await async_client.post(
            "/api/v1/fields/",
            json={
                "dataset_id": dataset_id,
                "parent_id": address_id,
                "name": "name",
            },
            headers=headers,
        )
        assert r.status_code == 201

    async def test_same_name_same_parent_rejected(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        nested_fields: dict,
    ):
        """Duplicate name among siblings is rejected."""
        parent = nested_fields["parent"]
        data = {
            "dataset_id": str(parent.dataset_id),
            "parent_id": str(parent.id),
            "name": "name",  # already exists under this parent
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.FIELD_ALREADY_EXISTS

    # ---- Validation ----

    async def test_create_field_parent_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_dataset: Dataset,
    ):
        data = {
            "dataset_id": str(test_dataset.id),
            "parent_id": str(uuid.uuid4()),
            "name": "orphan",
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.FIELD_PARENT_NOT_FOUND

    async def test_create_field_parent_dataset_mismatch(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_field: Field,
        second_dataset: Dataset,
    ):
        """Parent belongs to a different dataset."""
        data = {
            "dataset_id": str(second_dataset.id),
            "parent_id": str(test_field.id),  # belongs to test_dataset
            "name": "cross_dataset_child",
        }
        response = await async_client.post(
            "/api/v1/fields/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.FIELD_PARENT_DATASET_MISMATCH

    async def test_update_field_circular_reference(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        nested_fields: dict,
    ):
        """Setting parent_id to own child creates a circular reference."""
        parent = nested_fields["parent"]
        child = nested_fields["child_name"]

        # Try to set parent's parent_id to its own child
        response = await async_client.put(
            f"/api/v1/fields/{parent.id}",
            json={"parent_id": str(child.id), "row_version": 1},
            headers=superuser_token_headers,
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == errors.FIELD_CIRCULAR_REFERENCE

    # ---- Tree Operations ----

    async def test_get_field_tree(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        nested_fields: dict,
        test_dataset: Dataset,
    ):
        """Get full field tree for a dataset."""
        response = await async_client.get(
            f"/api/v1/fields/tree/{test_dataset.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        tree = response.json()
        assert len(tree) == 1  # one root: "customer"
        root = tree[0]
        assert root["name"] == "customer"
        assert len(root["children"]) == 2
        child_names = {c["name"] for c in root["children"]}
        assert child_names == {"name", "email"}
        # children have no children
        for child in root["children"]:
            assert child["children"] == []

    async def test_get_field_tree_dataset_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        response = await async_client.get(
            f"/api/v1/fields/tree/{uuid.uuid4()}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.DATASET_NOT_FOUND

    async def test_get_children(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        nested_fields: dict,
    ):
        """Get direct children of a field."""
        parent = nested_fields["parent"]
        response = await async_client.get(
            f"/api/v1/fields/{parent.id}/children",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        children = response.json()
        assert len(children) == 2
        child_names = {c["name"] for c in children}
        assert child_names == {"name", "email"}

    async def test_get_children_field_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        response = await async_client.get(
            f"/api/v1/fields/{uuid.uuid4()}/children",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.FIELD_NOT_FOUND

    # ---- Deletion (hard delete / CASCADE) ----

    async def test_delete_parent_cascades_to_children(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        nested_fields: dict,
    ):
        """Deleting a parent field cascades to its children (hard delete)."""
        parent = nested_fields["parent"]
        child_name = nested_fields["child_name"]
        child_email = nested_fields["child_email"]

        # Delete parent
        response = await async_client.delete(
            f"/api/v1/fields/{parent.id}", headers=superuser_token_headers
        )
        assert response.status_code == 200

        # Verify parent is gone
        response = await async_client.get(
            f"/api/v1/fields/{parent.id}", headers=superuser_token_headers
        )
        assert response.status_code == 404

        # Verify children are also gone (CASCADE)
        response = await async_client.get(
            f"/api/v1/fields/{child_name.id}", headers=superuser_token_headers
        )
        assert response.status_code == 404

        response = await async_client.get(
            f"/api/v1/fields/{child_email.id}", headers=superuser_token_headers
        )
        assert response.status_code == 404

    async def test_delete_leaf_child_keeps_parent(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        nested_fields: dict,
    ):
        """Deleting a leaf child does not affect parent or siblings."""
        parent = nested_fields["parent"]
        child_name = nested_fields["child_name"]
        child_email = nested_fields["child_email"]

        # Delete one child
        response = await async_client.delete(
            f"/api/v1/fields/{child_name.id}", headers=superuser_token_headers
        )
        assert response.status_code == 200

        # Parent still exists
        response = await async_client.get(
            f"/api/v1/fields/{parent.id}", headers=superuser_token_headers
        )
        assert response.status_code == 200

        # Sibling still exists
        response = await async_client.get(
            f"/api/v1/fields/{child_email.id}", headers=superuser_token_headers
        )
        assert response.status_code == 200
