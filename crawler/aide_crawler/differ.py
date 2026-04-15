"""Diff crawler output against metastore state.

classify_and_diff splits crawled datasets into:
  - to_apply: datasets absent in metastore (passed to applier unchanged)
  - DiffPayload: structured diff for existing and removed datasets,
    including per-field type changes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from aide_sdk import AideClient

from aide_crawler.normalizer import NormalizedDataset, NormalizedResult
from aide_crawler.type_cache import TypeCache
from aide_crawler.type_map import TypeChild, TypeNode


@dataclass
class DiffPayload:
    new_datasets_applied: list[dict[str, Any]] = field(default_factory=list)
    existing_datasets_diff: list[dict[str, Any]] = field(default_factory=list)
    removed_datasets: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, **asdict(self)}

    def counts(self) -> dict[str, int]:
        return {
            "new_datasets_applied": len(self.new_datasets_applied),
            "new_fields": sum(
                len(e["new_fields"]) for e in self.existing_datasets_diff
            ),
            "removed_fields": sum(
                len(e["removed_fields"]) for e in self.existing_datasets_diff
            ),
            "removed_datasets": len(self.removed_datasets),
            "type_changes": sum(
                len(e.get("type_changes", [])) for e in self.existing_datasets_diff
            ),
        }


async def _list_existing_datasets(
    client: AideClient, system_id: UUID
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        resp = await client.datasets.list(
            page=page, size=100, params={"system_id": str(system_id)}
        )
        for item in resp.items:
            ds = item.model_dump()
            out[ds["object_name"]] = ds
        if page >= resp.pages:
            break
        page += 1
    return out


async def _list_existing_fields(
    client: AideClient, dataset_id: Any
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        resp = await client.fields.list(
            page=page, size=100, params={"dataset_id": str(dataset_id)}
        )
        for item in resp.items:
            f = item.model_dump()
            out[f["name"]] = f
        if page >= resp.pages:
            break
        page += 1
    return out


async def _find_schema_v1_id(client: AideClient, dataset_id: Any) -> UUID | None:
    page = 1
    while True:
        resp = await client.dataset_schemas.list(
            page=page, size=100, params={"dataset_id": str(dataset_id)}
        )
        for item in resp.items:
            if item.version_num == 1:
                return item.id
        if page >= resp.pages:
            break
        page += 1
    return None


async def _bindings_by_field_id(
    client: AideClient, schema_id: UUID
) -> dict[UUID, dict[str, Any]]:
    out: dict[UUID, dict[str, Any]] = {}
    page = 1
    while True:
        resp = await client.field_bindings.list(
            page=page, size=100, params={"dataset_schema_id": str(schema_id)}
        )
        for item in resp.items:
            fb = item.model_dump()
            out[fb["field_id"]] = fb
        if page >= resp.pages:
            break
        page += 1
    return out


def _tree_to_node(tree: Any, type_cache: TypeCache) -> TypeNode:
    code = type_cache.code_for(tree.data_type_id) or "__unknown__"
    params = tree.type_params or {}
    children = [
        TypeChild(slot=c.slot or "", node=_tree_to_node(c, type_cache))
        for c in tree.children
    ]
    return TypeNode(data_type_code=code, type_params=params, children=children)


def _filter_node(node: TypeNode, type_cache: TypeCache) -> TypeNode:
    """Drop params that aren't in the data_type's params_schema.

    Mirrors what applier does before POSTing. Required so differ compares
    what is actually persisted, not what SA inspection produced.
    """
    allowed = type_cache.allowed_params(node.data_type_code)
    filtered_params = {k: v for k, v in node.type_params.items() if k in allowed}
    filtered_children = [
        TypeChild(slot=c.slot, node=_filter_node(c.node, type_cache))
        for c in node.children
    ]
    return TypeNode(
        data_type_code=node.data_type_code,
        type_params=filtered_params,
        children=filtered_children,
    )


def _nodes_equal(a: TypeNode, b: TypeNode) -> bool:
    if a.data_type_code != b.data_type_code:
        return False
    if (a.type_params or {}) != (b.type_params or {}):
        return False
    a_by_slot = {c.slot: c.node for c in a.children}
    b_by_slot = {c.slot: c.node for c in b.children}
    if set(a_by_slot) != set(b_by_slot):
        return False
    return all(_nodes_equal(a_by_slot[k], b_by_slot[k]) for k in a_by_slot)


def _flatten_root(node: TypeNode) -> dict[str, Any]:
    return {"code": node.data_type_code, "params": node.type_params or {}}


def _node_to_dict(node: TypeNode) -> dict[str, Any]:
    return {
        "code": node.data_type_code,
        "params": node.type_params or {},
        "children": [
            {"slot": c.slot, "node": _node_to_dict(c.node)} for c in node.children
        ],
    }


async def classify_and_diff(
    client: AideClient,
    system_id: UUID,
    normalized: NormalizedResult,
    type_cache: TypeCache,
) -> tuple[list[NormalizedDataset], DiffPayload]:
    """Split crawled datasets into (to_apply, diff_payload) with type-change detection."""
    existing = await _list_existing_datasets(client, system_id)
    existing_names = set(existing)
    crawled_names = {d.object_name for d in normalized.datasets}

    payload = DiffPayload()
    to_apply: list[NormalizedDataset] = [
        d for d in normalized.datasets if d.object_name not in existing_names
    ]

    for name in sorted(existing_names - crawled_names):
        payload.removed_datasets.append(
            {"object_name": name, "dataset_id": str(existing[name]["id"])}
        )

    for nd in normalized.datasets:
        if nd.object_name not in existing_names:
            continue
        ds = existing[nd.object_name]
        ds_id = ds["id"]
        existing_fields = await _list_existing_fields(client, ds_id)

        crawled_field_names = {f.name for f in nd.fields}
        new_fields = [
            {
                "name": f.name,
                "code": f.type_node.data_type_code,
                "params": f.type_node.type_params or {},
            }
            for f in nd.fields
            if f.name not in existing_fields
        ]
        removed_fields = [
            {"name": name, "field_id": str(existing_fields[name]["id"])}
            for name in sorted(set(existing_fields) - crawled_field_names)
        ]

        type_changes: list[dict[str, Any]] = []
        schema_id = await _find_schema_v1_id(client, ds_id)
        if schema_id is not None:
            bindings = await _bindings_by_field_id(client, schema_id)
            for nf in nd.fields:
                existing_field = existing_fields.get(nf.name)
                if existing_field is None:
                    continue
                binding = bindings.get(existing_field["id"])
                if binding is None:
                    continue
                ti_tree = await client.type_instances.get_tree(
                    binding["type_instance_id"]
                )
                current_node = _tree_to_node(ti_tree, type_cache)
                crawled_node = _filter_node(nf.type_node, type_cache)
                if not _nodes_equal(current_node, crawled_node):
                    type_changes.append(
                        {
                            "field_name": nf.name,
                            "field_id": str(existing_field["id"]),
                            "before": _flatten_root(current_node),
                            "after": _flatten_root(crawled_node),
                            "full_before": _node_to_dict(current_node),
                            "full_after": _node_to_dict(crawled_node),
                        }
                    )

        payload.existing_datasets_diff.append(
            {
                "object_name": nd.object_name,
                "dataset_id": str(ds_id),
                "new_fields": new_fields,
                "removed_fields": removed_fields,
                "type_changes": type_changes,
            }
        )

    return to_apply, payload
