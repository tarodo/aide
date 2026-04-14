from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from aide_sdk import AideClient

from aide_crawler.normalizer import NormalizedDataset, NormalizedField, NormalizedResult


@dataclass
class TypeChange:
    dataset_object_name: str
    field_name: str
    old_type: str
    new_type: str
    old_params: dict[str, Any]
    new_params: dict[str, Any]


@dataclass
class IndexChange:
    dataset_object_name: str
    index_name: str
    columns: list[str]
    is_unique: bool


@dataclass
class DiffResult:
    new_datasets: list[NormalizedDataset]
    removed_datasets: list[dict[str, Any]]
    new_fields: dict[str, list[NormalizedField]]
    removed_fields: dict[str, list[dict[str, Any]]]
    type_changes: list[TypeChange]
    new_indexes: dict[str, list[IndexChange]]
    removed_indexes: dict[str, list[IndexChange]]


async def compute_diff(
    client: AideClient,
    system_id: UUID,
    normalized: NormalizedResult,
) -> DiffResult:
    """Compare normalized crawl result against current metastore state."""

    existing_datasets: dict[str, dict[str, Any]] = {}
    page_num = 1
    while True:
        page = await client.datasets.list(
            page=page_num, size=100, params={"system_id": str(system_id)}
        )
        for item in page.items:
            ds = item.model_dump()
            existing_datasets[ds["object_name"]] = ds
        if page_num >= page.pages:
            break
        page_num += 1

    crawled_names = {d.object_name for d in normalized.datasets}
    existing_names = set(existing_datasets.keys())

    new_datasets = [
        d for d in normalized.datasets if d.object_name not in existing_names
    ]

    removed_datasets = [
        existing_datasets[name] for name in existing_names - crawled_names
    ]

    new_fields: dict[str, list[NormalizedField]] = {}
    removed_fields: dict[str, list[dict[str, Any]]] = {}
    type_changes: list[TypeChange] = []

    for nd in normalized.datasets:
        if nd.object_name not in existing_names:
            continue

        ds = existing_datasets[nd.object_name]
        ds_id = ds["id"]

        existing_field_map: dict[str, dict[str, Any]] = {}
        fp = 1
        while True:
            fpage = await client.fields.list(
                page=fp, size=100, params={"dataset_id": str(ds_id)}
            )
            for f in fpage.items:
                fd = f.model_dump()
                existing_field_map[fd["name"]] = fd
            if fp >= fpage.pages:
                break
            fp += 1

        crawled_field_names = {f.name for f in nd.fields}
        existing_field_names = set(existing_field_map.keys())

        nf = [f for f in nd.fields if f.name not in existing_field_names]
        if nf:
            new_fields[nd.object_name] = nf

        rf = [
            existing_field_map[name]
            for name in existing_field_names - crawled_field_names
        ]
        if rf:
            removed_fields[nd.object_name] = rf

    return DiffResult(
        new_datasets=new_datasets,
        removed_datasets=removed_datasets,
        new_fields=new_fields,
        removed_fields=removed_fields,
        type_changes=type_changes,
        new_indexes={},
        removed_indexes={},
    )
