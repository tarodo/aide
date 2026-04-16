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
from aide_sdk.exceptions import NotFoundError

from aide_crawler.normalizer import NormalizedDataset, NormalizedField, NormalizedResult
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


@dataclass
class FieldBindingSnapshot:
    """Reference to an existing FieldBinding's field + type_instance.

    Used by VersionedDatasetPlan to tell the applier which TypeInstance
    tree to reuse (verbatim) for an unchanged field in the new version.
    """

    field_id: UUID
    type_instance_id: UUID


@dataclass
class VersionedDatasetPlan:
    """Everything the applier needs to create the next DatasetSchema version.

    Built by classify_and_diff when a structural diff is detected against
    an existing dataset. current_version_num is the baseline (latest with
    bindings). next_version_num is max_version_num + 1 across all rows,
    so orphan version numbers are skipped.
    """

    dataset_id: UUID
    object_name: str
    current_version_num: int
    next_version_num: int
    all_fields: list[NormalizedField]  # post-change field set, in source order
    unchanged_field_bindings: dict[str, FieldBindingSnapshot]  # keyed by field name
    added_fields: list[NormalizedField]
    type_changed_fields: list[NormalizedField]
    removed_field_ids: list[UUID]


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


async def _find_baseline_schema(
    client: AideClient, dataset_id: Any
) -> tuple[UUID, int] | None:
    """Return (schema_id, version_num) for the latest schema version that has
    at least one FieldBinding. Skips orphan versions left behind by a
    partial prior crawl. Returns None if no non-orphan version exists.
    """
    best: tuple[UUID, int] | None = None
    page = 1
    while True:
        resp = await client.dataset_schemas.list(
            page=page, size=100, params={"dataset_id": str(dataset_id)}
        )
        for item in resp.items:
            bindings = await client.field_bindings.list(
                page=1, size=1, params={"dataset_schema_id": str(item.id)}
            )
            if not bindings.items:
                continue
            if best is None or item.version_num > best[1]:
                best = (item.id, item.version_num)
        if page >= resp.pages:
            break
        page += 1
    return best


async def _find_max_version_num(client: AideClient, dataset_id: Any) -> int:
    """Return max(version_num) across ALL DatasetSchema rows for this dataset,
    including orphans. Returns 0 if no rows exist.
    """
    max_num = 0
    page = 1
    while True:
        resp = await client.dataset_schemas.list(
            page=page, size=100, params={"dataset_id": str(dataset_id)}
        )
        for item in resp.items:
            if item.version_num > max_num:
                max_num = item.version_num
        if page >= resp.pages:
            break
        page += 1
    return max_num


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
) -> tuple[list[NormalizedDataset], list[VersionedDatasetPlan], DiffPayload]:
    """Split crawled datasets into (to_apply_new, to_version, diff_payload).

    - to_apply_new: datasets absent in metastore → go through apply_new_datasets
    - to_version: existing datasets with a structural diff → apply_versioned_datasets
    - diff_payload: human-readable audit; also persisted to crawl_runs.diff_payload
    """
    existing = await _list_existing_datasets(client, system_id)
    existing_names = set(existing)
    crawled_names = {d.object_name for d in normalized.datasets}

    payload = DiffPayload()
    to_apply: list[NormalizedDataset] = [
        d for d in normalized.datasets if d.object_name not in existing_names
    ]
    to_version: list[VersionedDatasetPlan] = []

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
        new_fields_desc = [
            {
                "name": f.name,
                "code": f.type_node.data_type_code,
                "params": f.type_node.type_params or {},
            }
            for f in nd.fields
            if f.name not in existing_fields
        ]
        removed_fields_desc = [
            {"name": name, "field_id": str(existing_fields[name]["id"])}
            for name in sorted(set(existing_fields) - crawled_field_names)
        ]

        baseline = await _find_baseline_schema(client, ds_id)
        type_changes: list[dict[str, Any]] = []
        unchanged_snapshots: dict[str, FieldBindingSnapshot] = {}
        type_changed_nfs: list[NormalizedField] = []
        current_version_num: int | None = None

        if baseline is not None:
            schema_id, current_version_num = baseline
            bindings = await _bindings_by_field_id(client, schema_id)
            for nf in nd.fields:
                existing_field = existing_fields.get(nf.name)
                if existing_field is None:
                    continue  # added field — handled separately
                binding = bindings.get(existing_field["id"])
                if binding is None:
                    continue
                try:
                    ti_tree = await client.type_instances.get_tree(
                        binding["type_instance_id"]
                    )
                except NotFoundError:
                    current_node = TypeNode(
                        data_type_code="__missing__", type_params={}
                    )
                else:
                    current_node = _filter_node(
                        _tree_to_node(ti_tree, type_cache), type_cache
                    )
                crawled_node = _filter_node(nf.type_node, type_cache)
                if _nodes_equal(current_node, crawled_node):
                    unchanged_snapshots[nf.name] = FieldBindingSnapshot(
                        field_id=existing_field["id"],
                        type_instance_id=binding["type_instance_id"],
                    )
                else:
                    type_changed_nfs.append(nf)
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
                "current_version_num": current_version_num,
                "new_version_num": None,  # filled by runner after applier succeeds
                "new_fields": new_fields_desc,
                "removed_fields": removed_fields_desc,
                "type_changes": type_changes,
            }
        )

        has_diff = bool(new_fields_desc or removed_fields_desc or type_changes)
        if not has_diff or baseline is None:
            continue

        assert current_version_num is not None  # implied by baseline is not None
        added_nfs = [nf for nf in nd.fields if nf.name not in existing_fields]
        max_version_num = await _find_max_version_num(client, ds_id)
        to_version.append(
            VersionedDatasetPlan(
                dataset_id=ds_id,
                object_name=nd.object_name,
                current_version_num=current_version_num,
                next_version_num=max_version_num + 1,
                all_fields=list(nd.fields),
                unchanged_field_bindings=unchanged_snapshots,
                added_fields=added_nfs,
                type_changed_fields=type_changed_nfs,
                removed_field_ids=[
                    existing_fields[name]["id"]
                    for name in sorted(set(existing_fields) - crawled_field_names)
                ],
            )
        )

    return to_apply, to_version, payload
