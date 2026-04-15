# Crawler Type-Change Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crawler detects when an existing field's type has changed and reports each change (before → after). Read-only: no auto-apply; the engineer performs the schema update manually.

**Architecture:** The differ already lists existing datasets and compares crawled field sets (added/removed). Add a third axis: for every field present on both sides, reconstruct the currently-bound `TypeNode` tree from the metastore, compare it to the newly-resolved crawled `TypeNode`, and emit a `type_changes` entry if they differ. Reconstruction walks the existing `TypeInstanceTree` returned by a new SDK method. Comparison is a recursive structural check of `(data_type_code, type_params, children-by-slot)`.

**Tech Stack:** Python 3.13, async `aide-sdk` (httpx), `pytest`/`pytest-asyncio`. No DB migrations, no backend changes — backend already exposes `GET /api/v1/type-instances/{id}/tree`.

---

## File Structure

- Modify: `sdk/aide_sdk/resources/type_instances.py` — add `get_tree(obj_id)` method returning `TypeInstanceTree`.
- Modify: `crawler/aide_crawler/type_cache.py` — keep existing `id → code` resolution but also expose it as a public method (`code_for(id)`).
- Modify: `crawler/aide_crawler/differ.py` — accept a `TypeCache`, fetch current schema + bindings + TI trees, emit `type_changes` entries.
- Modify: `crawler/aide_crawler/reporter.py` — render `type_changes` in both `text` and `json` outputs.
- Modify: `crawler/aide_crawler/runner.py` — pass the already-loaded `TypeCache` into `classify_and_diff`.
- Modify/Create: `crawler/tests/test_differ.py` — add cases covering unchanged, added, removed, changed (leaf + array element) fields.
- Modify: `crawler/tests/test_reporter.py` — cover `type_changes` rendering.
- Modify: `crawler/tests/test_runner.py` — adapt to the new `classify_and_diff` signature.

---

## Reference: comparison semantics

A crawled `TypeNode` equals a metastore-reconstructed one iff:
- `data_type_code` matches (case-sensitive).
- `type_params` compare equal, treating an empty dict and `None` as the same.
- Children compare by `slot` (order-independent), recursively.

A change entry has the shape:

```python
{
    "field_name": "name",
    "field_id": "<uuid>",
    "before": {"code": "varchar", "params": {"length": 255}},  # flattened root — see below
    "after":  {"code": "text",    "params": {}},
}
```

For compound types (array), we still emit one entry per field and flatten only the root in `before`/`after` summaries. Full trees are not rendered in the text report because that reads poorly. JSON report includes full trees under a separate key `full_before` / `full_after` for tooling.

---

### Task 1: SDK — add `get_tree` to `type_instances` resource

**Files:**
- Modify: `sdk/aide_sdk/resources/type_instances.py`
- Modify: `sdk/tests/` (create `test_type_instances.py` if absent, otherwise extend)

- [ ] **Step 1: Extend the resource**

```python
# sdk/aide_sdk/resources/type_instances.py
from uuid import UUID

from aide_schemas.type_instance import (
    TypeInstanceCreate,
    TypeInstanceRead,
    TypeInstanceTree,
    TypeInstanceUpdate,
)
from aide_sdk.resources.base import BaseResource


class TypeInstancesResource(
    BaseResource[TypeInstanceCreate, TypeInstanceRead, TypeInstanceUpdate]
):
    _path = "/api/v1/type-instances"
    _read_schema = TypeInstanceRead

    async def get_tree(self, obj_id: UUID) -> TypeInstanceTree:
        data = await self._http.get(f"{self._path}/{obj_id}/tree")
        return TypeInstanceTree.model_validate(data)
```

- [ ] **Step 2: Unit test (mock HTTP)**

Add a test that stubs `self._http.get` to return a JSON fixture of a `TypeInstanceTree` with one child, and asserts that `get_tree` returns a validated `TypeInstanceTree` with the correct `children[0].slot` and `data_type_id`.

```python
# sdk/tests/test_type_instances.py
import uuid
from unittest.mock import AsyncMock

import pytest

from aide_schemas.type_instance import TypeInstanceTree
from aide_sdk.resources.type_instances import TypeInstancesResource


@pytest.mark.asyncio
async def test_get_tree_validates_response():
    now = "2026-04-15T10:00:00Z"
    child_id = str(uuid.uuid4())
    root_id = str(uuid.uuid4())
    dt_array = str(uuid.uuid4())
    dt_text = str(uuid.uuid4())

    payload = {
        "id": root_id,
        "data_type_id": dt_array,
        "type_params": None,
        "slot": None,
        "row_version": 0,
        "created_at": now,
        "updated_at": now,
        "children": [
            {
                "id": child_id,
                "data_type_id": dt_text,
                "type_params": None,
                "slot": "item",
                "row_version": 0,
                "created_at": now,
                "updated_at": now,
                "children": [],
            }
        ],
    }

    http = AsyncMock()
    http.get = AsyncMock(return_value=payload)
    resource = TypeInstancesResource(http)

    tree = await resource.get_tree(uuid.UUID(root_id))

    assert isinstance(tree, TypeInstanceTree)
    assert str(tree.id) == root_id
    assert len(tree.children) == 1
    assert tree.children[0].slot == "item"
    assert str(tree.children[0].data_type_id) == dt_text
    http.get.assert_awaited_once_with(f"/api/v1/type-instances/{root_id}/tree")
```

- [ ] **Step 3: Run SDK tests**

```bash
cd sdk && uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add sdk/aide_sdk/resources/type_instances.py sdk/tests/test_type_instances.py
git commit -m "feat(sdk): add TypeInstances.get_tree"
```

---

### Task 2: TypeCache — expose reverse lookup

**Files:**
- Modify: `crawler/aide_crawler/type_cache.py`
- Modify: `crawler/tests/test_type_cache.py`

- [ ] **Step 1: Add the reverse index and a `code_for` method**

Replace the existing `TypeCache` dataclass body. Keep external method `resolve(code)` unchanged; add `code_for(id)` and populate `_code_by_id` in `load`.

```python
# crawler/aide_crawler/type_cache.py
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from aide_crawler.errors import TypeNotInFlavorError


@dataclass
class TypeCache:
    flavor_code: str | None = None
    _by_code: dict[str, uuid.UUID] = field(default_factory=dict)
    _code_by_id: dict[uuid.UUID, str] = field(default_factory=dict)
    _params_schema_by_code: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    async def load(
        cls,
        client,
        *,
        flavor_id: uuid.UUID,
        flavor_code: str | None = None,
    ) -> "TypeCache":
        cache = cls(flavor_code=flavor_code)
        page_num = 1
        while True:
            resp = await client.data_types.list(
                page=page_num,
                size=100,
                params={"system_flavor_id": str(flavor_id)},
            )
            for item in resp.items:
                cache._by_code[item.code] = item.id
                cache._code_by_id[item.id] = item.code
                cache._params_schema_by_code[item.code] = item.params_schema or {}
            if page_num >= resp.pages:
                break
            page_num += 1
        return cache

    def resolve(self, code: str) -> uuid.UUID:
        try:
            return self._by_code[code]
        except KeyError:
            raise TypeNotInFlavorError(code, self.flavor_code) from None

    def code_for(self, data_type_id: uuid.UUID) -> str | None:
        """Reverse lookup: id → code. Returns None for unknown ids.

        Unknown ids can happen if the metastore holds a data_type that
        no longer belongs to the flavor (stale record); differ treats
        such bindings as "unknown type" rather than crashing.
        """
        return self._code_by_id.get(data_type_id)

    def allowed_params(self, code: str) -> set[str]:
        return set(self._params_schema_by_code.get(code, {}).keys())

    def __len__(self) -> int:
        return len(self._by_code)
```

- [ ] **Step 2: Test the reverse lookup**

Append a test to `crawler/tests/test_type_cache.py`:

```python
@pytest.mark.asyncio
async def test_code_for_reverse_lookup():
    flavor_id = uuid.uuid4()
    id_int = uuid.uuid4()
    client = _ClientStub([_Item(id_int, "integer")])
    cache = await TypeCache.load(client, flavor_id=flavor_id, flavor_code="postgres14")

    assert cache.code_for(id_int) == "integer"
    assert cache.code_for(uuid.uuid4()) is None
```

- [ ] **Step 3: Run tests**

```bash
cd crawler && uv run pytest tests/test_type_cache.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add crawler/aide_crawler/type_cache.py crawler/tests/test_type_cache.py
git commit -m "feat(crawler): TypeCache reverse lookup code_for(id)"
```

---

### Task 3: Differ — detect and emit `type_changes`

**Files:**
- Modify: `crawler/aide_crawler/differ.py`

- [ ] **Step 1: Rewrite `differ.py` with type-change detection**

```python
# crawler/aide_crawler/differ.py
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
    """Reconstruct a TypeNode from a TypeInstanceTree using TypeCache reverse lookup."""
    code = type_cache.code_for(tree.data_type_id) or "__unknown__"
    params = tree.type_params or {}
    children = [
        TypeChild(slot=c.slot or "", node=_tree_to_node(c, type_cache))
        for c in tree.children
    ]
    return TypeNode(data_type_code=code, type_params=params, children=children)


def _nodes_equal(a: TypeNode, b: TypeNode) -> bool:
    """Structural equality: code, params (None == {}), and children by slot."""
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
                if not _nodes_equal(current_node, nf.type_node):
                    type_changes.append(
                        {
                            "field_name": nf.name,
                            "field_id": str(existing_field["id"]),
                            "before": _flatten_root(current_node),
                            "after": _flatten_root(nf.type_node),
                            "full_before": _node_to_dict(current_node),
                            "full_after": _node_to_dict(nf.type_node),
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
```

- [ ] **Step 2: Run existing differ tests to confirm current fixtures need updating (expected)**

```bash
cd crawler && uv run pytest tests/test_differ.py -v
```

Expected: failures because `classify_and_diff` signature changed (added `type_cache`). That's addressed in Task 4.

- [ ] **Step 3: Defer the commit**

Do NOT commit yet — Task 4 adjusts test fixtures so that the full suite stays green as one unit.

---

### Task 4: Differ tests — unchanged / added / removed / changed coverage

**Files:**
- Modify: `crawler/tests/test_differ.py`

- [ ] **Step 1: Rewrite the test file**

The test needs mocks for `datasets`, `fields`, `dataset_schemas`, `field_bindings`, and `type_instances.get_tree`. Use simple ad-hoc stubs rather than `AsyncMock` everywhere — clearer.

```python
# crawler/tests/test_differ.py
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from aide_crawler.differ import classify_and_diff
from aide_crawler.normalizer import NormalizedDataset, NormalizedField, NormalizedResult
from aide_crawler.type_cache import TypeCache
from aide_crawler.type_map import TypeChild, TypeNode


def _page(items, pages=1):
    return type("P", (), {"items": items, "pages": pages})()


def _model(**kw):
    """Object that quacks like a pydantic read-model (has .model_dump and .id etc.)."""

    class _M:
        def __init__(self, **k):
            self.__dict__.update(k)

        def model_dump(self):
            return dict(self.__dict__)

    return _M(**kw)


def _nf(name: str, code: str, position: int = 0, children=None) -> NormalizedField:
    return NormalizedField(
        name=name,
        path=name,
        nullable=True,
        position=position,
        type_node=TypeNode(
            data_type_code=code, type_params={}, children=children or []
        ),
    )


def _nd(object_name: str, fields: list[NormalizedField]) -> NormalizedDataset:
    parts = object_name.split(".")
    schema = parts[-2] if len(parts) >= 2 else "public"
    table = parts[-1]
    return NormalizedDataset(
        object_name=object_name,
        catalog_name=parts[0] if len(parts) == 3 else None,
        schema_name=schema,
        table_name=table,
        is_view=False,
        pk_columns=["id"],
        uq_constraints=[],
        comment=None,
        fields=fields,
        indexes=[],
        foreign_keys=[],
    )


class _Cache(TypeCache):
    def __init__(self, id_to_code: dict[uuid.UUID, str]):
        super().__init__(flavor_code="postgres14")
        self._by_code = {code: id_ for id_, code in id_to_code.items()}
        self._code_by_id = dict(id_to_code)


def _ti_tree(data_type_id, slot=None, type_params=None, children=None):
    return type(
        "T",
        (),
        {
            "id": uuid.uuid4(),
            "data_type_id": data_type_id,
            "slot": slot,
            "type_params": type_params,
            "children": children or [],
        },
    )()


def _build_client(
    *,
    existing_datasets: list,
    existing_fields_by_ds: dict,
    schemas_by_ds: dict,
    bindings_by_schema: dict,
    trees_by_ti: dict,
):
    c = AsyncMock()
    c.datasets = AsyncMock()
    c.datasets.list = AsyncMock(return_value=_page(existing_datasets))

    async def _fields_list(*, page=1, size=100, params=None):
        ds_id = params["dataset_id"]
        return _page(existing_fields_by_ds.get(ds_id, []))

    c.fields = AsyncMock()
    c.fields.list = AsyncMock(side_effect=_fields_list)

    async def _schemas_list(*, page=1, size=100, params=None):
        ds_id = params["dataset_id"]
        return _page(schemas_by_ds.get(ds_id, []))

    c.dataset_schemas = AsyncMock()
    c.dataset_schemas.list = AsyncMock(side_effect=_schemas_list)

    async def _bindings_list(*, page=1, size=100, params=None):
        schema_id = params["dataset_schema_id"]
        return _page(bindings_by_schema.get(schema_id, []))

    c.field_bindings = AsyncMock()
    c.field_bindings.list = AsyncMock(side_effect=_bindings_list)

    async def _get_tree(ti_id):
        return trees_by_ti[ti_id]

    c.type_instances = AsyncMock()
    c.type_instances.get_tree = AsyncMock(side_effect=_get_tree)

    return c


SYSTEM_ID = uuid.uuid4()


@pytest.mark.asyncio
async def test_unchanged_field_produces_no_type_change():
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    field_id = uuid.uuid4()
    ti_id = uuid.uuid4()
    dt_int = uuid.uuid4()

    cache = _Cache({dt_int: "integer"})

    client = _build_client(
        existing_datasets=[
            _model(id=ds_id, object_name="target.demo.t"),
        ],
        existing_fields_by_ds={str(ds_id): [_model(id=field_id, name="id")]},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=field_id, type_instance_id=ti_id)]
        },
        trees_by_ti={ti_id: _ti_tree(dt_int)},
    )

    nd = _nd("target.demo.t", [_nf("id", "integer")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    entry = payload.existing_datasets_diff[0]
    assert entry["type_changes"] == []
    assert entry["new_fields"] == []
    assert entry["removed_fields"] == []


@pytest.mark.asyncio
async def test_varchar_to_text_reports_type_change():
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    field_id = uuid.uuid4()
    ti_id = uuid.uuid4()
    dt_varchar = uuid.uuid4()
    dt_text = uuid.uuid4()

    cache = _Cache({dt_varchar: "varchar", dt_text: "text"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): [_model(id=field_id, name="name")]},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=field_id, type_instance_id=ti_id)]
        },
        trees_by_ti={ti_id: _ti_tree(dt_varchar, type_params={"length": 255})},
    )

    nd = _nd("target.demo.t", [_nf("name", "text")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    changes = payload.existing_datasets_diff[0]["type_changes"]
    assert len(changes) == 1
    change = changes[0]
    assert change["field_name"] == "name"
    assert change["before"] == {"code": "varchar", "params": {"length": 255}}
    assert change["after"] == {"code": "text", "params": {}}


@pytest.mark.asyncio
async def test_array_element_change_reports_type_change():
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    field_id = uuid.uuid4()
    root_ti = uuid.uuid4()
    dt_array = uuid.uuid4()
    dt_int = uuid.uuid4()
    dt_bigint = uuid.uuid4()

    cache = _Cache({dt_array: "array", dt_int: "integer", dt_bigint: "bigint"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): [_model(id=field_id, name="nums")]},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=field_id, type_instance_id=root_ti)]
        },
        trees_by_ti={
            root_ti: _ti_tree(
                dt_array,
                children=[_ti_tree(dt_int, slot="item")],
            )
        },
    )

    nd = _nd(
        "target.demo.t",
        [
            _nf(
                "nums",
                "array",
                children=[
                    TypeChild(
                        slot="item",
                        node=TypeNode(data_type_code="bigint", type_params={}),
                    )
                ],
            )
        ],
    )
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    changes = payload.existing_datasets_diff[0]["type_changes"]
    assert len(changes) == 1
    assert changes[0]["before"] == {"code": "array", "params": {}}
    assert changes[0]["after"] == {"code": "array", "params": {}}
    assert changes[0]["full_before"]["children"][0]["node"]["code"] == "integer"
    assert changes[0]["full_after"]["children"][0]["node"]["code"] == "bigint"


@pytest.mark.asyncio
async def test_added_field_is_new_not_type_change():
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    cache = _Cache({uuid.uuid4(): "integer"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): []},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={str(schema_id): []},
        trees_by_ti={},
    )

    nd = _nd("target.demo.t", [_nf("id", "integer")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    entry = payload.existing_datasets_diff[0]
    assert entry["new_fields"][0]["name"] == "id"
    assert entry["type_changes"] == []
```

- [ ] **Step 2: Run the differ tests**

```bash
cd crawler && uv run pytest tests/test_differ.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit differ + tests together**

```bash
git add crawler/aide_crawler/differ.py crawler/tests/test_differ.py
git commit -m "feat(crawler): differ detects type changes on existing fields"
```

---

### Task 5: Reporter — render `type_changes` in text and JSON

**Files:**
- Modify: `crawler/aide_crawler/reporter.py`
- Modify: `crawler/tests/test_reporter.py`

- [ ] **Step 1: Update the text renderer**

Find the loop that renders `entry` under "Existing datasets with changes". After the `new_fields` / `removed_fields` lines, add a `type_changes` block:

```python
for change in entry.get("type_changes", []):
    before = change["before"]
    after = change["after"]
    before_str = _fmt_type(before)
    after_str = _fmt_type(after)
    out.write(f"      ~ {change['field_name']}: {before_str} -> {after_str}\n")
```

Add a helper near the top of the module:

```python
def _fmt_type(t: dict) -> str:
    params = t.get("params") or {}
    if not params:
        return t["code"]
    kv = ", ".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{t['code']}({kv})"
```

Example rendered block:

```
  * target.demo.products
      ~ name: varchar(length=255) -> text
```

Don't render `full_before`/`full_after` in text — the flat summary is enough for a human. JSON output already carries them via `asdict` in `DiffPayload.to_dict()`.

- [ ] **Step 2: Update reporter tests**

Add a case to `crawler/tests/test_reporter.py`:

```python
def test_report_renders_type_changes_in_text():
    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "target.demo.products",
                "dataset_id": "00000000-0000-0000-0000-000000000001",
                "new_fields": [],
                "removed_fields": [],
                "type_changes": [
                    {
                        "field_name": "name",
                        "field_id": "00000000-0000-0000-0000-000000000002",
                        "before": {"code": "varchar", "params": {"length": 255}},
                        "after": {"code": "text", "params": {}},
                        "full_before": {},
                        "full_after": {},
                    }
                ],
            }
        ],
    )
    buf = io.StringIO()
    render_text(payload, applied=[], out=buf)
    text = buf.getvalue()
    assert "~ name: varchar(length=255) -> text" in text
```

(Adapt the import names — `render_text` / `DiffPayload` — to match what `reporter.py` actually exports. Read the file first.)

- [ ] **Step 3: Run reporter tests**

```bash
cd crawler && uv run pytest tests/test_reporter.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add crawler/aide_crawler/reporter.py crawler/tests/test_reporter.py
git commit -m "feat(crawler): reporter renders type_changes"
```

---

### Task 6: Runner — thread `TypeCache` into `classify_and_diff`

**Files:**
- Modify: `crawler/aide_crawler/runner.py`
- Modify: `crawler/tests/test_runner.py`

- [ ] **Step 1: Pass `type_cache` when calling `classify_and_diff`**

In `runner.py`, find the line `to_apply, payload = await classify_and_diff(client, system_id, normalized)` and update to `await classify_and_diff(client, system_id, normalized, type_cache)`. The `type_cache` variable is already loaded earlier in `run_crawl`.

- [ ] **Step 2: Update runner tests**

In `crawler/tests/test_runner.py`, find the mocks for `classify_and_diff` (or the places that touch it indirectly). The existing fixtures should continue to work because `classify_and_diff` is called internally with a `TypeCache` that's also built from mocked `data_types.list`. If tests fail with arity errors, pass through the extra argument in the fixture; do not redesign the test.

- [ ] **Step 3: Run full crawler suite**

```bash
cd crawler && uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add crawler/aide_crawler/runner.py crawler/tests/test_runner.py
git commit -m "chore(crawler): wire TypeCache into classify_and_diff"
```

---

### Task 7: Lint + format sweep

- [ ] **Step 1: Run format + check**

```bash
make format && make check
```

Expected: ruff clean, black clean. Mypy may print 2 pre-existing errors (yaml stubs, sdk/datasets.py) — acceptable.

- [ ] **Step 2: Commit if any changes**

```bash
git status
# if changes:
git add -A
git commit -m "chore(crawler): format after type-change detection"
```

---

### Task 8: Manual end-to-end verification

**Files:** none

- [ ] **Step 1: Confirm the target PG14 is up with the schema from the previous crawl already applied**

```bash
docker ps | grep aide-crawler-target-pg14
```

If not running:

```bash
./scripts/manual_test/start_pg14.sh
./scripts/manual_test/seed_target.sh
```

If the metastore is fresh, run a first crawl to populate the baseline:

```bash
cd crawler
uv run aide-crawler crawl \
  --system-code demo_pg14 \
  --connection-url "postgresql+psycopg://crawler:crawler@localhost:5434/target" \
  --metastore-url http://localhost:8000 \
  --metastore-user admin@example.com \
  --metastore-password changeme \
  --schemas demo \
  --format text
```

- [ ] **Step 2: Change a column type on the target**

```bash
docker exec -i aide-crawler-target-pg14 psql -U crawler -d target <<'SQL'
ALTER TABLE demo.products ALTER COLUMN "name" TYPE varchar(100) USING "name"::varchar(100);
SQL
```

- [ ] **Step 3: Rerun the crawler and verify it reports the change**

```bash
cd crawler
uv run aide-crawler crawl \
  --system-code demo_pg14 \
  --connection-url "postgresql+psycopg://crawler:crawler@localhost:5434/target" \
  --metastore-url http://localhost:8000 \
  --metastore-user admin@example.com \
  --metastore-password changeme \
  --schemas demo \
  --format text
```

Expected output contains:

```
  * target.demo.products
      ~ name: text -> varchar(length=100)
```

And summary has `type_changes: 1`.

- [ ] **Step 4: Revert the change so the target is clean**

```bash
docker exec -i aide-crawler-target-pg14 psql -U crawler -d target <<'SQL'
ALTER TABLE demo.products ALTER COLUMN "name" TYPE text USING "name"::text;
SQL
```

If everything reports as expected, the feature is done. If output diverges, return to the relevant task.

---

## Self-Review Notes

- **Spec coverage:** detect change (T3), cache reverse lookup (T2), SDK fetch tree (T1), reporter (T5), wiring (T6), e2e proof (T8). ✅
- **Type consistency:** `TypeNode`/`TypeChild` use unchanged. `classify_and_diff` gains one parameter — `type_cache: TypeCache`. `code_for(id)` returns `str | None` to tolerate stale metastore rows.
- **No placeholders.**
