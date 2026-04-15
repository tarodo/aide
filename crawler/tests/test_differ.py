"""Tests for classify_and_diff (Task 9)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from aide_crawler.differ import DiffPayload, classify_and_diff
from aide_crawler.normalizer import NormalizedDataset, NormalizedField, NormalizedResult
from aide_crawler.type_map import TypeNode

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _item(**kw):
    """Lightweight stand-in for a Pydantic model that exposes model_dump()."""
    obj = type("I", (), {})()
    obj.model_dump = lambda self=obj: kw
    for k, v in kw.items():
        setattr(obj, k, v)
    return obj


def _page(items, pages=1):
    p = MagicMock()
    p.items = items
    p.pages = pages
    return p


def _make_client(datasets_pages, fields_pages_by_ds_id=None):
    """Build a minimal AideClient mock.

    datasets_pages: list of page payloads for client.datasets.list
    fields_pages_by_ds_id: dict[uuid-str -> list of page payloads] for client.fields.list
    """
    client = MagicMock()

    # datasets.list returns pages in order
    ds_call_results = [_page(p) for p in datasets_pages]
    client.datasets.list = AsyncMock(side_effect=ds_call_results)

    if fields_pages_by_ds_id is not None:
        # fields.list side-effect: looks at dataset_id param passed in kw
        call_tracker: dict[str, list] = {
            k: list(v) for k, v in fields_pages_by_ds_id.items()
        }

        async def fields_list_side_effect(**kw):
            ds_id = kw.get("params", {}).get("dataset_id", "")
            pages_for_ds = call_tracker.get(ds_id, [])
            if pages_for_ds:
                return pages_for_ds.pop(0)
            return _page([])

        client.fields.list = AsyncMock(side_effect=fields_list_side_effect)
    else:
        client.fields.list = AsyncMock(return_value=_page([]))

    return client


def _nd(object_name, fields=None):
    return NormalizedDataset(
        object_name=object_name,
        catalog_name="testdb",
        schema_name=object_name.split(".")[0],
        table_name=object_name.split(".")[1],
        is_view=False,
        pk_columns=["id"],
        uq_constraints=[],
        comment=None,
        fields=fields or [],
        indexes=[],
        foreign_keys=[],
    )


def _nf(name, code="integer", params=None):
    return NormalizedField(
        name=name,
        path=name,
        nullable=False,
        position=0,
        type_node=TypeNode(data_type_code=code, type_params=params or {}),
    )


SYSTEM_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# a. All-new — empty existing, two crawled datasets → both in to_apply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_new():
    client = _make_client(datasets_pages=[[]])  # no existing datasets
    normalized = NormalizedResult(
        dialect_name="postgresql",
        datasets=[_nd("public.users"), _nd("public.orders")],
    )

    to_apply, payload = await classify_and_diff(client, SYSTEM_ID, normalized)

    assert len(to_apply) == 2
    assert {d.object_name for d in to_apply} == {"public.users", "public.orders"}
    assert payload.new_datasets_applied == []
    assert payload.existing_datasets_diff == []
    assert payload.removed_datasets == []


# ---------------------------------------------------------------------------
# b. Existing with new field — crawl returns same dataset with 2 fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_with_new_field():
    ds_id = str(uuid.uuid4())
    client = _make_client(
        datasets_pages=[[_item(id=ds_id, object_name="public.users")]],
        fields_pages_by_ds_id={
            ds_id: [_page([_item(id=str(uuid.uuid4()), name="id")])]
        },
    )
    normalized = NormalizedResult(
        dialect_name="postgresql",
        datasets=[_nd("public.users", fields=[_nf("id"), _nf("email", "varchar")])],
    )

    to_apply, payload = await classify_and_diff(client, SYSTEM_ID, normalized)

    assert to_apply == []
    assert len(payload.existing_datasets_diff) == 1
    entry = payload.existing_datasets_diff[0]
    assert entry["object_name"] == "public.users"
    assert len(entry["new_fields"]) == 1
    assert entry["new_fields"][0]["name"] == "email"
    assert entry["new_fields"][0]["code"] == "varchar"
    assert entry["removed_fields"] == []
    assert entry["type_changes"] == []


# ---------------------------------------------------------------------------
# c. Existing with removed field — crawl missing a field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_with_removed_field():
    ds_id = str(uuid.uuid4())
    field_id = str(uuid.uuid4())
    client = _make_client(
        datasets_pages=[[_item(id=ds_id, object_name="public.users")]],
        fields_pages_by_ds_id={
            ds_id: [
                _page(
                    [
                        _item(id=str(uuid.uuid4()), name="id"),
                        _item(id=field_id, name="old_column"),
                    ]
                )
            ]
        },
    )
    normalized = NormalizedResult(
        dialect_name="postgresql",
        datasets=[_nd("public.users", fields=[_nf("id")])],  # old_column gone
    )

    to_apply, payload = await classify_and_diff(client, SYSTEM_ID, normalized)

    assert to_apply == []
    entry = payload.existing_datasets_diff[0]
    assert entry["new_fields"] == []
    assert len(entry["removed_fields"]) == 1
    assert entry["removed_fields"][0]["name"] == "old_column"
    assert entry["removed_fields"][0]["field_id"] == field_id


# ---------------------------------------------------------------------------
# d. Removed dataset — exists in metastore but not in crawl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_removed_dataset():
    ds_id = str(uuid.uuid4())
    client = _make_client(
        datasets_pages=[[_item(id=ds_id, object_name="public.legacy")]],
    )
    normalized = NormalizedResult(
        dialect_name="postgresql",
        datasets=[],  # legacy not crawled
    )

    to_apply, payload = await classify_and_diff(client, SYSTEM_ID, normalized)

    assert to_apply == []
    assert payload.existing_datasets_diff == []
    assert len(payload.removed_datasets) == 1
    assert payload.removed_datasets[0]["object_name"] == "public.legacy"
    assert payload.removed_datasets[0]["dataset_id"] == ds_id


# ---------------------------------------------------------------------------
# e. to_dict() tags schema_version 1; counts() returns correct sums
# ---------------------------------------------------------------------------


def test_diff_payload_to_dict():
    payload = DiffPayload(
        new_datasets_applied=[{"object_name": "public.a"}],
        existing_datasets_diff=[
            {
                "object_name": "public.b",
                "dataset_id": "some-id",
                "new_fields": [{"name": "x", "code": "integer", "params": {}}],
                "removed_fields": [{"name": "y", "field_id": "fid"}],
                "type_changes": [],
            }
        ],
        removed_datasets=[{"object_name": "public.c", "dataset_id": "did"}],
    )

    d = payload.to_dict()
    assert d["schema_version"] == 1
    assert "new_datasets_applied" in d
    assert "existing_datasets_diff" in d
    assert "removed_datasets" in d


def test_diff_payload_counts():
    payload = DiffPayload(
        new_datasets_applied=[{"object_name": "public.a"}, {"object_name": "public.b"}],
        existing_datasets_diff=[
            {
                "object_name": "public.c",
                "dataset_id": "id1",
                "new_fields": [{"name": "x", "code": "integer", "params": {}}],
                "removed_fields": [],
                "type_changes": [],
            },
            {
                "object_name": "public.d",
                "dataset_id": "id2",
                "new_fields": [],
                "removed_fields": [{"name": "y", "field_id": "fid"}],
                "type_changes": [],
            },
        ],
        removed_datasets=[{"object_name": "public.e", "dataset_id": "id3"}],
    )

    counts = payload.counts()
    assert counts["new_datasets_applied"] == 2
    assert counts["new_fields"] == 1
    assert counts["removed_fields"] == 1
    assert counts["removed_datasets"] == 1
    assert counts["type_changes"] == 0
