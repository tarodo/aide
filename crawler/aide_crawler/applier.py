# crawler/aide_crawler/applier.py
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from aide_schemas.dataset import DatasetRdbmsCreate
from aide_schemas.dataset_schema import DatasetSchemaCreate
from aide_schemas.field import FieldCreate
from aide_schemas.field_binding import FieldBindingCreate
from aide_schemas.type_instance import TypeInstanceCreate

from aide_crawler.normalizer import NormalizedDataset, NormalizedField
from aide_crawler.type_cache import TypeCache
from aide_crawler.type_map import TypeNode


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
        DatasetSchemaCreate(  # type: ignore[call-arg]
            dataset_id=dataset_id, version_num=1
        )
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


def _flatten_tree(
    node: TypeNode,
    *,
    path: tuple[str, ...],
    depth: int,
    slot: str | None,
    out: list[
        tuple[int, tuple[str, ...], tuple[str, ...] | None, TypeNode, str | None]
    ],
) -> None:
    """Recursively flatten a TypeNode tree into a list of (depth, path, parent_path, node, slot) records."""
    parent_path: tuple[str, ...] | None = path[:-1] if depth > 0 else None
    out.append((depth, path, parent_path, node, slot))
    for child in node.children:
        _flatten_tree(
            child.node,
            path=path + (child.slot,),
            depth=depth + 1,
            slot=child.slot,
            out=out,
        )


async def _batch_create_type_trees(
    client,
    *,
    field_root_nodes: list[tuple[uuid.UUID, TypeNode]],
    type_cache: TypeCache,
) -> dict[uuid.UUID, uuid.UUID]:
    """Flatten all trees, group by depth, and issue one create_many call per level.

    Returns {field_id: root_type_instance_id}.
    """
    flat: list[
        tuple[int, tuple[str, ...], tuple[str, ...] | None, TypeNode, str | None]
    ] = []
    field_id_by_root_path: dict[tuple[str, ...], uuid.UUID] = {}

    for field_id, root in field_root_nodes:
        root_path = (str(field_id),)
        field_id_by_root_path[root_path] = field_id
        _flatten_tree(root, path=root_path, depth=0, slot=None, out=flat)

    by_depth: dict[
        int,
        list[tuple[int, tuple[str, ...], tuple[str, ...] | None, TypeNode, str | None]],
    ] = defaultdict(list)
    for rec in flat:
        by_depth[rec[0]].append(rec)

    path_to_id: dict[tuple[str, ...], uuid.UUID] = {}
    field_root_ti: dict[uuid.UUID, uuid.UUID] = {}

    for depth in sorted(by_depth.keys()):
        level = by_depth[depth]
        items: list[TypeInstanceCreate] = []
        for _depth, _path, parent_path, node, slot in level:
            data_type_id = type_cache.resolve(node.data_type_code)
            allowed = type_cache.allowed_params(node.data_type_code)
            filtered = {k: v for k, v in node.type_params.items() if k in allowed}
            items.append(
                TypeInstanceCreate(  # type: ignore[call-arg]
                    data_type_id=data_type_id,
                    type_params=filtered or None,
                    parent_id=path_to_id[parent_path] if parent_path else None,
                    slot=slot,
                )
            )
        created = await client.type_instances.create_many(items)
        for (_d, path, _pp, _n, _s), ti in zip(level, created):
            if path in path_to_id:
                raise RuntimeError(
                    f"Duplicate TypeInstance path {path}; sibling slots must be unique"
                )
            path_to_id[path] = ti.id
            if path in field_id_by_root_path:
                field_root_ti[field_id_by_root_path[path]] = ti.id

    return field_root_ti


async def apply_new_datasets(
    client,
    *,
    system_id: uuid.UUID,
    datasets: list[NormalizedDataset],
    type_cache: TypeCache,
    existing_dataset_ids: dict[str, uuid.UUID] | None = None,
) -> list[AppliedDataset]:
    """Write the full ER chain for each new dataset.

    Idempotent for the *structural* chain: safe to rerun after a partial
    failure. A field whose binding already exists is skipped — including
    when the column's type has changed upstream. The stale TypeInstance
    tree is left untouched; differ surfaces the change in its report but
    nothing here rewrites it. In-place TypeInstance updates are not yet
    supported.
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

        # Phase 1: batch-create any missing fields.
        to_create_fields: list[FieldCreate] = [
            FieldCreate(  # type: ignore[call-arg]
                dataset_id=dataset_id,
                name=nf.name,
                path=nf.path,
            )
            for nf in nd.fields
            if nf.name not in existing_fields
        ]
        field_map: dict[str, uuid.UUID] = dict(existing_fields)
        if to_create_fields:
            created_fields = await client.fields.create_many(to_create_fields)
            for cf in created_fields:
                field_map[cf.name] = cf.id

        # Phase 2: batch-create type_instance trees for fields that still need a binding.
        fields_to_bind: list[tuple[uuid.UUID, TypeNode]] = []
        nf_by_field_id: list[tuple[uuid.UUID, NormalizedField]] = []
        for nf in nd.fields:
            field_id = field_map[nf.name]
            if field_id in existing_bindings:
                continue
            fields_to_bind.append((field_id, nf.type_node))
            nf_by_field_id.append((field_id, nf))

        field_root_ti: dict[uuid.UUID, uuid.UUID] = {}
        if fields_to_bind:
            field_root_ti = await _batch_create_type_trees(
                client, field_root_nodes=fields_to_bind, type_cache=type_cache
            )

        # Phase 3: batch-create all missing field bindings.
        bindings_to_create: list[FieldBindingCreate] = [
            FieldBindingCreate(  # type: ignore[call-arg]
                field_id=field_id,
                dataset_schema_id=schema_id,
                type_instance_id=field_root_ti[field_id],
                position=nf.position,
                is_nullable=nf.nullable,
            )
            for field_id, nf in nf_by_field_id
        ]
        if bindings_to_create:
            await client.field_bindings.create_many(bindings_to_create)

        # fields_written counts all fields accounted for (both already-bound and newly-bound).
        fields_written = len(nd.fields)

        results.append(
            AppliedDataset(
                object_name=nd.object_name,
                dataset_id=dataset_id,
                dataset_schema_id=schema_id,
                fields_count=fields_written,
            )
        )

    return results
