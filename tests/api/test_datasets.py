from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import System, SystemFlavor, SystemKind, User


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


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="ds_super.user@example.com",
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
    kind = SystemKind(code="RDBMS_DS_TEST", name="RDBMS for Dataset Test")
    flavor = SystemFlavor(code="PG_DS_TEST", name="Postgres for DS Test", kind=kind)
    system = System(code="PROD_DB_DS_TEST", name="Prod DB for DS Test", flavor=flavor)
    transactional_session.add_all([kind, flavor, system])
    await transactional_session.commit()
    return system


@pytest.mark.asyncio
class TestDatasetAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_rdbms_dataset(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        data = {
            "kind": "rdbms",
            "system_id": str(test_system.id),
            "object_name": "customers_table",
            "layer": "raw",
            "schema_name": "public",
            "table_name": "customers",
        }
        response = await async_client.post(
            "/api/v1/datasets/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["kind"] == "rdbms"
        assert res_json["object_name"] == "customers_table"
        assert res_json["table_name"] == "customers"
        return res_json["id"]

    async def test_create_kafka_dataset(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        data = {
            "kind": "kafka",
            "system_id": str(test_system.id),
            "object_name": "orders_topic",
            "layer": "source",
            "topic": "e-commerce.orders",
            "format": "AVRO",
            "partitions": 12,
            "retention_ms": 604800000,
            "key_columns": ["order_id"],
        }
        response = await async_client.post(
            "/api/v1/datasets/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["kind"] == "kafka"
        assert res_json["topic"] == "e-commerce.orders"

    async def test_get_dataset(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        # First, create a dataset to get
        create_data = {
            "kind": "rdbms",
            "system_id": str(test_system.id),
            "object_name": "products_table",
            "layer": "raw",
            "schema_name": "public",
            "table_name": "products",
        }
        create_response = await async_client.post(
            "/api/v1/datasets/", json=create_data, headers=superuser_token_headers
        )
        assert create_response.status_code == 201
        dataset_id = create_response.json()["id"]

        # Now, get it
        get_response = await async_client.get(
            f"/api/v1/datasets/{dataset_id}", headers=superuser_token_headers
        )
        assert get_response.status_code == 200
        res_json = get_response.json()
        assert res_json["id"] == dataset_id
        assert res_json["kind"] == "rdbms"
        assert res_json["table_name"] == "products"

    async def test_get_all_datasets_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        # Create at least one dataset
        await self.test_create_rdbms_dataset(
            async_client, superuser_token_headers, test_system
        )

        response = await async_client.get(
            "/api/v1/datasets/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1
        assert "kind" in data["items"][0]

    async def test_update_dataset(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        # Create a dataset
        create_data = {
            "kind": "rdbms",
            "system_id": str(test_system.id),
            "object_name": "inventory_table",
            "layer": "raw",
            "schema_name": "inventory",
            "table_name": "stock",
        }
        create_response = await async_client.post(
            "/api/v1/datasets/", json=create_data, headers=superuser_token_headers
        )
        dataset_id = create_response.json()["id"]

        # Update it
        update_data = {
            "kind": "rdbms",
            "layer": "core",
            "table_name": "dim_stock",
            "row_version": 1,
        }
        update_response = await async_client.patch(
            f"/api/v1/datasets/{dataset_id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert update_response.status_code == 200
        res_json = update_response.json()
        assert res_json["layer"] == "core"
        assert res_json["table_name"] == "dim_stock"
        assert res_json["schema_name"] == "inventory"  # Unchanged

    async def test_update_dataset_kind_mismatch_fails(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        # Create an rdbms dataset
        create_data = {
            "kind": "rdbms",
            "system_id": str(test_system.id),
            "object_name": "inventory_table_for_kind_test",
            "layer": "raw",
            "schema_name": "inventory",
            "table_name": "stock",
        }
        create_response = await async_client.post(
            "/api/v1/datasets/", json=create_data, headers=superuser_token_headers
        )
        dataset_id = create_response.json()["id"]

        # Try to update it with a 'kafka' kind
        update_data = {"kind": "kafka", "topic": "new_topic", "row_version": 1}
        update_response = await async_client.patch(
            f"/api/v1/datasets/{dataset_id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert update_response.status_code == 400
        assert update_response.json()["error_code"] == errors.DATASET_KIND_MISMATCH

    async def test_update_dataset_version_conflict(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        # Create a dataset
        create_data = {
            "kind": "rdbms",
            "system_id": str(test_system.id),
            "object_name": "conflict_test_table",
            "layer": "raw",
            "schema_name": "test",
            "table_name": "conflict",
        }
        create_response = await async_client.post(
            "/api/v1/datasets/", json=create_data, headers=superuser_token_headers
        )
        dataset_id = create_response.json()["id"]

        # First update succeeds
        response = await async_client.patch(
            f"/api/v1/datasets/{dataset_id}",
            json={"kind": "rdbms", "layer": "core", "row_version": 1},
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["row_version"] == 2

        # Second update with stale row_version
        response = await async_client.patch(
            f"/api/v1/datasets/{dataset_id}",
            json={"kind": "rdbms", "layer": "kafka", "row_version": 1},
            headers=superuser_token_headers,
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "VERSION_CONFLICT"

    async def test_delete_dataset(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        # Create a dataset
        create_data = {
            "kind": "sftp",
            "system_id": str(test_system.id),
            "object_name": "daily_sales_csv",
            "path": "/uploads/sales.csv",
            "file_format": "csv",
        }
        create_response = await async_client.post(
            "/api/v1/datasets/", json=create_data, headers=superuser_token_headers
        )
        dataset_id = create_response.json()["id"]

        # Delete it
        delete_response = await async_client.delete(
            f"/api/v1/datasets/{dataset_id}", headers=superuser_token_headers
        )
        assert delete_response.status_code == 200

        # Verify it's gone
        get_response = await async_client.get(
            f"/api/v1/datasets/{dataset_id}", headers=superuser_token_headers
        )
        assert get_response.status_code == 404

    async def test_upstream_downstream_links(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        a = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "ud_a", "source"
        )
        b = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "ud_b", "raw"
        )
        c = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "ud_c", "core"
        )
        await async_client.post(
            "/api/v1/dataset-links/",
            json={"source_dataset_id": a, "target_dataset_id": b},
            headers=superuser_token_headers,
        )
        await async_client.post(
            "/api/v1/dataset-links/",
            json={"source_dataset_id": b, "target_dataset_id": c},
            headers=superuser_token_headers,
        )

        up = await async_client.get(
            f"/api/v1/datasets/{b}/upstream-links", headers=superuser_token_headers
        )
        down = await async_client.get(
            f"/api/v1/datasets/{b}/downstream-links", headers=superuser_token_headers
        )
        assert up.status_code == 200 and len(up.json()) == 1
        assert down.status_code == 200 and len(down.json()) == 1

    async def test_unmapped_fields(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        src = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "um_s", "source"
        )
        tgt = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "um_t", "raw"
        )
        # Target dataset with two non-tech fields and one tech field
        f1 = await _create_field(async_client, superuser_token_headers, tgt, "a")
        await _create_field(async_client, superuser_token_headers, tgt, "b")
        await _create_field(
            async_client, superuser_token_headers, tgt, "etl_ts", origin="tech"
        )
        sf = await _create_field(async_client, superuser_token_headers, src, "a")
        link_id = (
            await async_client.post(
                "/api/v1/dataset-links/",
                json={"source_dataset_id": src, "target_dataset_id": tgt},
                headers=superuser_token_headers,
            )
        ).json()["id"]
        await async_client.post(
            f"/api/v1/dataset-links/{link_id}/field-links/",
            json={
                "dataset_link_id": link_id,
                "source_field_id": sf,
                "target_field_id": f1,
            },
            headers=superuser_token_headers,
        )

        resp = await async_client.get(
            f"/api/v1/datasets/{tgt}/unmapped-fields",
            headers=superuser_token_headers,
        )
        assert resp.status_code == 200
        names = {f["name"] for f in resp.json()}
        assert names == {"b"}

    async def test_lineage_endpoints_404_on_missing_dataset(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        missing = "00000000-0000-0000-0000-000000000000"
        for path in ("upstream-links", "downstream-links", "unmapped-fields"):
            resp = await async_client.get(
                f"/api/v1/datasets/{missing}/{path}",
                headers=superuser_token_headers,
            )
            assert resp.status_code == status.HTTP_404_NOT_FOUND, path
            assert resp.json()["error_code"] == errors.DATASET_NOT_FOUND

    async def test_apply_tech_template_layer_mismatch(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        tpl = (
            await async_client.post(
                "/api/v1/tech-field-templates/",
                json={
                    "code": "apply_mm_v1",
                    "name": "Apply MM",
                    "layer": "core",
                },
                headers=superuser_token_headers,
            )
        ).json()
        ds_id = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "apply_mm_tgt", "raw"
        )
        resp = await async_client.post(
            f"/api/v1/datasets/{ds_id}/apply-tech-template",
            json={"template_id": tpl["id"]},
            headers=superuser_token_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["error_code"] == "TECH_FIELD_TEMPLATE_LAYER_MISMATCH"

    async def test_apply_tech_template_unresolvable_flavor(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        """When the dataset's flavor has no resolver mapping, the apply returns 400.

        This exercises the TECH_TYPE_CODE_NOT_RESOLVABLE path at the HTTP layer.
        The test_system fixture's flavor code (e.g. FL_DS_API) is NOT in the
        resolver YAML (which only has postgres14), so resolution fails cleanly.
        """
        tpl = (
            await async_client.post(
                "/api/v1/tech-field-templates/",
                json={
                    "code": "apply_happy_v1",
                    "name": "Apply Happy",
                    "layer": "core",
                },
                headers=superuser_token_headers,
            )
        ).json()
        await async_client.post(
            f"/api/v1/tech-field-templates/{tpl['id']}/fields",
            json={
                "template_id": tpl["id"],
                "name": "valid_from",
                "type_code": "TIMESTAMP",
                "order": 0,
            },
            headers=superuser_token_headers,
        )
        ds_id = await _create_dataset(
            async_client, superuser_token_headers, test_system.id, "apply_tgt", "core"
        )
        resp = await async_client.post(
            f"/api/v1/datasets/{ds_id}/apply-tech-template",
            json={"template_id": tpl["id"]},
            headers=superuser_token_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["error_code"] == "TECH_TYPE_CODE_NOT_RESOLVABLE"
