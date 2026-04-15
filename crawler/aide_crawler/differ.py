"""Diff crawler output against metastore state.

classify_and_diff splits crawled datasets into:
  - to_apply: datasets absent in metastore (passed to applier unchanged)
  - DiffPayload: structured diff for existing and removed datasets

TODO: type_changes stays empty in v1. Computing it requires reading the
current DatasetSchema's FieldBindings and the TypeInstance each binding
points at, then comparing against the newly-resolved (code, params).
Track as follow-up.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from aide_sdk import AideClient

from aide_crawler.normalizer import NormalizedDataset, NormalizedResult


@dataclass
class DiffPayload:
    new_datasets_applied: list[dict[str, Any]] = field(default_factory=list)
    existing_datasets_diff: list[dict[str, Any]] = field(default_factory=list)
    removed_datasets: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return schema_version-tagged JSON-ready dict."""
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


async def classify_and_diff(
    client: AideClient,
    system_id: UUID,
    normalized: NormalizedResult,
) -> tuple[list[NormalizedDataset], DiffPayload]:
    """Split crawled datasets into (to_apply, diff_payload).

    - to_apply: datasets absent in metastore; passed to applier as-is.
    - diff_payload: structured diff for existing + removed datasets.

    TODO: type_changes stays empty in v1. Computing it requires reading
    the current DatasetSchema's FieldBindings and the TypeInstance each
    binding points at, then comparing against the newly-resolved (code,
    params). Track as follow-up.
    """
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
                "code": f.type_mapping.data_type_code,
                "params": f.type_mapping.type_params or {},
            }
            for f in nd.fields
            if f.name not in existing_fields
        ]
        removed_fields = [
            {"name": name, "field_id": str(existing_fields[name]["id"])}
            for name in sorted(set(existing_fields) - crawled_field_names)
        ]
        payload.existing_datasets_diff.append(
            {
                "object_name": nd.object_name,
                "dataset_id": str(ds_id),
                "new_fields": new_fields,
                "removed_fields": removed_fields,
                "type_changes": [],  # TODO: see module docstring
            }
        )

    return to_apply, payload
