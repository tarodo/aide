from __future__ import annotations

import uuid
from dataclasses import dataclass

from aide_schemas.dataset import DatasetRdbmsCreate
from aide_schemas.dataset_schema import DatasetSchemaCreate
from aide_schemas.field import FieldCreate
from aide_schemas.field_binding import FieldBindingCreate
from aide_schemas.type_instance import TypeInstanceCreate

from aide_crawler.normalizer import NormalizedDataset
from aide_crawler.type_cache import TypeCache


@dataclass
class AppliedDataset:
    object_name: str
    dataset_id: uuid.UUID
    dataset_schema_id: uuid.UUID
    fields_count: int


async def _find_or_create_schema_v1(client, *, dataset_id: uuid.UUID) -> uuid.UUID:
    """Return the id of the version_num=1 schema, creating it if absent."""
    page_num = 1
    while True:
        resp = await client.dataset_schemas.list(
            page=page_num,
            size=100,
            params={"dataset_id": str(dataset_id)},
        )
        for item in resp.items:
            if item.version_num == 1:
                return item.id
        if page_num >= resp.pages:
            break
        page_num += 1

    created = await client.dataset_schemas.create(
        DatasetSchemaCreate(dataset_id=dataset_id, version_num=1)
    )
    return created.id


async def _list_fields_map(client, *, dataset_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Return {field_name: field_id} for all fields of the dataset."""
    result: dict[str, uuid.UUID] = {}
    page_num = 1
    while True:
        resp = await client.fields.list(
            page=page_num,
            size=100,
            params={"dataset_id": str(dataset_id)},
        )
        for item in resp.items:
            result[item.name] = item.id
        if page_num >= resp.pages:
            break
        page_num += 1
    return result


async def _list_bindings_field_ids(client, *, schema_id: uuid.UUID) -> set[uuid.UUID]:
    """Return set of field_ids already bound to the given schema."""
    result: set[uuid.UUID] = set()
    page_num = 1
    while True:
        resp = await client.field_bindings.list(
            page=page_num,
            size=100,
            params={"dataset_schema_id": str(schema_id)},
        )
        for item in resp.items:
            result.add(item.field_id)
        if page_num >= resp.pages:
            break
        page_num += 1
    return result


async def apply_new_datasets(
    client,
    *,
    system_id: uuid.UUID,
    datasets: list[NormalizedDataset],
    type_cache: TypeCache,
    existing_dataset_ids: dict[str, uuid.UUID] | None = None,
) -> list[AppliedDataset]:
    """Write the full ER chain for each new dataset.

    Idempotent: safe to rerun after a partial failure.
    """
    existing_dataset_ids = existing_dataset_ids or {}
    results: list[AppliedDataset] = []

    for nd in datasets:
        # --- Dataset ---
        if nd.object_name in existing_dataset_ids:
            dataset_id = existing_dataset_ids[nd.object_name]
        else:
            uq = {"items": nd.uq_constraints} if nd.uq_constraints else None
            created_ds = await client.datasets.create(
                DatasetRdbmsCreate(
                    kind="rdbms",
                    system_id=system_id,
                    object_name=nd.object_name,
                    catalog_name=nd.catalog_name,
                    schema_name=nd.schema_name,
                    table_name=nd.table_name,
                    is_view=nd.is_view,
                    pk_columns=nd.pk_columns,
                    uq_constraints=uq,
                )
            )
            dataset_id = created_ds.id

        # --- DatasetSchema v1 ---
        schema_id = await _find_or_create_schema_v1(client, dataset_id=dataset_id)

        # --- Fields ---
        existing_fields = await _list_fields_map(client, dataset_id=dataset_id)
        existing_bindings = await _list_bindings_field_ids(client, schema_id=schema_id)

        fields_written = 0
        for nf in nd.fields:
            if nf.name in existing_fields:
                field_id = existing_fields[nf.name]
            else:
                created_field = await client.fields.create(
                    FieldCreate(
                        dataset_id=dataset_id,
                        name=nf.name,
                        path=nf.path,
                    )
                )
                field_id = created_field.id

            if field_id in existing_bindings:
                fields_written += 1
                continue

            data_type_id = type_cache.resolve(nf.type_mapping.data_type_code)
            type_params = nf.type_mapping.type_params or None
            ti = await client.type_instances.create(
                TypeInstanceCreate(
                    data_type_id=data_type_id,
                    type_params=type_params,
                )
            )
            await client.field_bindings.create(
                FieldBindingCreate(
                    field_id=field_id,
                    dataset_schema_id=schema_id,
                    type_instance_id=ti.id,
                    position=nf.position,
                    is_nullable=nf.nullable,
                )
            )
            fields_written += 1

        results.append(
            AppliedDataset(
                object_name=nd.object_name,
                dataset_id=dataset_id,
                dataset_schema_id=schema_id,
                fields_count=fields_written,
            )
        )

    return results
