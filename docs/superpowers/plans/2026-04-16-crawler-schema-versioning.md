# Crawler Schema Versioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the RDBMS crawler so that on any structural diff (added/removed/type-changed field) against an existing dataset, it creates a new `DatasetSchema` version with a full `FieldBinding` set — instead of only persisting the diff to `crawl_runs.diff_payload`.

**Architecture:** Purely additive wiring in the `crawler/` package. Differ gains two version-aware helpers (`_find_baseline_schema`, `_find_max_version_num`) and emits a list of `VersionedDatasetPlan` alongside the existing `to_apply` and `DiffPayload`. Applier gains `apply_versioned_datasets` that issues the existing 3-call pattern (POST `/dataset-schemas/` → POST `/type-instances/batch` → POST `/field-bindings/batch`), reusing existing `TypeInstance` IDs for unchanged fields. Runner calls it after `apply_new_datasets`. Reporter adds a "Versioned Datasets" section. No backend/SDK/schemas/alembic changes.

**Tech Stack:** Python 3.13, pytest + pytest-asyncio, unittest.mock.AsyncMock (existing crawler test idioms), `aide_sdk` client, `aide_schemas` DTOs, `uv` for package management.

**Reference spec:** [docs/superpowers/specs/2026-04-16-crawler-schema-versioning-design.md](../specs/2026-04-16-crawler-schema-versioning-design.md)

**Test command (for this package):**

```bash
cd crawler && uv run pytest tests/ -v
```

(All tasks use this command. The crawler package's tests do not require Docker or the metastore DB — they are pure unit tests against mocked `AideClient`.)

---

## Task 1: Replace `_find_schema_v1_id` with baseline + max-version helpers in differ

**Files:**
- Modify: `crawler/aide_crawler/differ.py` (replace helper at lines 84–96, update call site at line 216)
- Test: `crawler/tests/test_differ.py`

**What this does:** Adds the two version-aware lookups the rest of the feature relies on. Keeps `classify_and_diff`'s return type unchanged (still 2-tuple) — later tasks extend the return type. No behaviour change yet for the diff semantics visible to the runner.

- [ ] **Step 1.1: Write failing tests for the two helpers**

Append to `crawler/tests/test_differ.py` (at the very end of the file, after `test_diff_payload_counts_aggregates_all_axes`):

```python
# ---------------------------------------------------------------------------
# Baseline + max-version helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_baseline_schema_picks_latest_with_bindings():
    """Two versions, both with bindings → baseline is the higher version_num."""
    from aide_crawler.differ import _find_baseline_schema

    ds_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()
    field_id = uuid.uuid4()

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={
            str(ds_id): [
                _model(id=v1_id, version_num=1),
                _model(id=v2_id, version_num=2),
            ]
        },
        bindings_by_schema={
            str(v1_id): [_model(field_id=field_id, type_instance_id=uuid.uuid4())],
            str(v2_id): [_model(field_id=field_id, type_instance_id=uuid.uuid4())],
        },
        trees_by_ti={},
    )

    result = await _find_baseline_schema(client, ds_id)
    assert result == (v2_id, 2)


@pytest.mark.asyncio
async def test_find_baseline_schema_skips_orphan():
    """v1 has bindings, v2 is orphan (no bindings) → baseline is v1."""
    from aide_crawler.differ import _find_baseline_schema

    ds_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()
    field_id = uuid.uuid4()

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={
            str(ds_id): [
                _model(id=v1_id, version_num=1),
                _model(id=v2_id, version_num=2),
            ]
        },
        bindings_by_schema={
            str(v1_id): [_model(field_id=field_id, type_instance_id=uuid.uuid4())],
            str(v2_id): [],
        },
        trees_by_ti={},
    )

    result = await _find_baseline_schema(client, ds_id)
    assert result == (v1_id, 1)


@pytest.mark.asyncio
async def test_find_baseline_schema_returns_none_when_all_orphan():
    """Every version has zero bindings → None."""
    from aide_crawler.differ import _find_baseline_schema

    ds_id = uuid.uuid4()
    v1_id = uuid.uuid4()

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={str(ds_id): [_model(id=v1_id, version_num=1)]},
        bindings_by_schema={str(v1_id): []},
        trees_by_ti={},
    )

    result = await _find_baseline_schema(client, ds_id)
    assert result is None


@pytest.mark.asyncio
async def test_find_baseline_schema_returns_none_when_no_schemas():
    """Dataset has no DatasetSchema rows at all → None."""
    from aide_crawler.differ import _find_baseline_schema

    ds_id = uuid.uuid4()

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={str(ds_id): []},
        bindings_by_schema={},
        trees_by_ti={},
    )

    result = await _find_baseline_schema(client, ds_id)
    assert result is None


@pytest.mark.asyncio
async def test_find_max_version_num_returns_highest_across_all():
    """Max is computed over ALL rows, including orphans above the baseline."""
    from aide_crawler.differ import _find_max_version_num

    ds_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()  # orphan (no bindings)
    v5_id = uuid.uuid4()  # orphan (no bindings)

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={
            str(ds_id): [
                _model(id=v1_id, version_num=1),
                _model(id=v2_id, version_num=2),
                _model(id=v5_id, version_num=5),
            ]
        },
        bindings_by_schema={},
        trees_by_ti={},
    )

    result = await _find_max_version_num(client, ds_id)
    assert result == 5


@pytest.mark.asyncio
async def test_find_max_version_num_returns_zero_when_no_schemas():
    """No rows → 0 (so next allocation starts at 1)."""
    from aide_crawler.differ import _find_max_version_num

    ds_id = uuid.uuid4()

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={str(ds_id): []},
        bindings_by_schema={},
        trees_by_ti={},
    )

    result = await _find_max_version_num(client, ds_id)
    assert result == 0
```

- [ ] **Step 1.2: Run new tests to confirm they fail**

Run:

```bash
cd crawler && uv run pytest tests/test_differ.py -v -k "find_baseline_schema or find_max_version_num"
```

Expected: ImportError (can't import `_find_baseline_schema`) or AttributeError. All 6 new tests FAIL.

- [ ] **Step 1.3: Implement the helpers and update the call site**

Edit `crawler/aide_crawler/differ.py`. Replace the existing `_find_schema_v1_id` function (lines 84–96) with:

```python
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
```

Then update the single call site at line 216. Replace:

```python
        schema_id = await _find_schema_v1_id(client, ds_id)
```

with:

```python
        baseline = await _find_baseline_schema(client, ds_id)
        schema_id = baseline[0] if baseline else None
```

- [ ] **Step 1.4: Run all differ tests to confirm PASS**

Run:

```bash
cd crawler && uv run pytest tests/test_differ.py -v
```

Expected: all tests pass. The 6 new helper tests PASS, existing tests continue to PASS (the old tests seeded `version_num=1` schemas with at least one binding each, so the new baseline logic picks them up exactly like the old `_find_schema_v1_id` did).

- [ ] **Step 1.5: Run format + lint**

Run:

```bash
make format && make check
```

Expected: no errors. Fix any ruff/black warnings before committing.

- [ ] **Step 1.6: Commit**

```bash
git add crawler/aide_crawler/differ.py crawler/tests/test_differ.py
git commit -m "feat(crawler): add version-aware schema lookup helpers

Replace _find_schema_v1_id with _find_baseline_schema (latest version
with bindings, skipping orphans) and _find_max_version_num (max across
all rows, including orphans). Prepares differ for multi-version schema
support; call site behaviour is unchanged when v1 is the only non-orphan
version, which is every existing dataset today."
```

---

## Task 2: Introduce `VersionedDatasetPlan` and extend `classify_and_diff` return type

**Files:**
- Modify: `crawler/aide_crawler/differ.py` (add dataclasses, extend return type, build plans)
- Modify: `crawler/aide_crawler/runner.py` (unpack 3-tuple; `to_version` is unused at this point — that's wired in Task 4)
- Test: `crawler/tests/test_differ.py`, `crawler/tests/test_runner.py`

**What this does:** Threads the per-dataset plan through the differ return value so later tasks (applier + runner) have structured input. No apply behaviour yet. Existing differ tests update to unpack three values. Runner tests update for the same reason.

- [ ] **Step 2.1: Write failing tests for plan construction**

Append to `crawler/tests/test_differ.py`:

```python
# ---------------------------------------------------------------------------
# VersionedDatasetPlan construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_and_diff_emits_no_plan_when_no_changes():
    """Existing dataset, no field diff → not in to_version list."""
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    field_id = uuid.uuid4()
    ti_id = uuid.uuid4()
    dt_int = uuid.uuid4()
    cache = _Cache({dt_int: "integer"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): [_model(id=field_id, name="id")]},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=field_id, type_instance_id=ti_id)]
        },
        trees_by_ti={ti_id: _ti_tree(dt_int)},
    )

    nd = _nd("target.demo.t", [_nf("id", "integer")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    to_apply, to_version, _ = await classify_and_diff(
        client, SYSTEM_ID, normalized, cache
    )
    assert to_apply == []
    assert to_version == []


@pytest.mark.asyncio
async def test_classify_and_diff_builds_plan_on_added_field():
    """Added field → plan with added_fields, unchanged_field_bindings for kept field."""
    from aide_crawler.differ import VersionedDatasetPlan

    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    dt_int = uuid.uuid4()
    cache = _Cache({dt_int: "integer"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): [_model(id=keep_id, name="id")]},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=keep_id, type_instance_id=keep_ti)]
        },
        trees_by_ti={keep_ti: _ti_tree(dt_int)},
    )

    nd = _nd(
        "target.demo.t",
        [_nf("id", "integer", position=0), _nf("email", "integer", position=1)],
    )
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, to_version, payload = await classify_and_diff(
        client, SYSTEM_ID, normalized, cache
    )
    assert len(to_version) == 1
    plan = to_version[0]
    assert isinstance(plan, VersionedDatasetPlan)
    assert plan.dataset_id == ds_id
    assert plan.current_version_num == 1
    assert plan.next_version_num == 2
    assert [f.name for f in plan.all_fields] == ["id", "email"]
    assert [f.name for f in plan.added_fields] == ["email"]
    assert plan.removed_field_ids == []
    assert [f.name for f in plan.type_changed_fields] == []
    assert set(plan.unchanged_field_bindings.keys()) == {"id"}
    snap = plan.unchanged_field_bindings["id"]
    assert snap.field_id == keep_id
    assert snap.type_instance_id == keep_ti
    # DiffPayload entry carries current_version_num
    assert payload.existing_datasets_diff[0]["current_version_num"] == 1
    assert payload.existing_datasets_diff[0]["new_version_num"] is None


@pytest.mark.asyncio
async def test_classify_and_diff_plan_marks_type_changed_fields():
    """Field with changed type goes into type_changed_fields, not unchanged."""
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    field_id = uuid.uuid4()
    ti_id = uuid.uuid4()
    dt_int = uuid.uuid4()
    dt_bigint = uuid.uuid4()
    cache = _Cache({dt_int: "integer", dt_bigint: "bigint"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): [_model(id=field_id, name="n")]},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=field_id, type_instance_id=ti_id)]
        },
        trees_by_ti={ti_id: _ti_tree(dt_int)},
    )

    nd = _nd("target.demo.t", [_nf("n", "bigint", position=0)])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, to_version, _ = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    assert len(to_version) == 1
    plan = to_version[0]
    assert [f.name for f in plan.type_changed_fields] == ["n"]
    assert "n" not in plan.unchanged_field_bindings


@pytest.mark.asyncio
async def test_classify_and_diff_plan_captures_removed_fields():
    """Removed field ID is recorded in plan.removed_field_ids."""
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    drop_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    dt_int = uuid.uuid4()
    cache = _Cache({dt_int: "integer"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={
            str(ds_id): [
                _model(id=keep_id, name="id"),
                _model(id=drop_id, name="legacy"),
            ]
        },
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=keep_id, type_instance_id=keep_ti)]
        },
        trees_by_ti={keep_ti: _ti_tree(dt_int)},
    )

    nd = _nd("target.demo.t", [_nf("id", "integer", position=0)])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, to_version, _ = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    assert len(to_version) == 1
    plan = to_version[0]
    assert plan.removed_field_ids == [drop_id]


@pytest.mark.asyncio
async def test_classify_and_diff_plan_next_version_skips_orphan_numbers():
    """v1 has bindings (baseline), v2 is orphan → next = 3, not 2."""
    ds_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    dt_int = uuid.uuid4()
    cache = _Cache({dt_int: "integer"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): [_model(id=keep_id, name="id")]},
        schemas_by_ds={
            str(ds_id): [
                _model(id=v1_id, version_num=1),
                _model(id=v2_id, version_num=2),
            ]
        },
        bindings_by_schema={
            str(v1_id): [_model(field_id=keep_id, type_instance_id=keep_ti)],
            str(v2_id): [],  # orphan
        },
        trees_by_ti={keep_ti: _ti_tree(dt_int)},
    )

    nd = _nd(
        "target.demo.t",
        [_nf("id", "integer", position=0), _nf("email", "integer", position=1)],
    )
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, to_version, _ = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    assert len(to_version) == 1
    plan = to_version[0]
    assert plan.current_version_num == 1
    assert plan.next_version_num == 3


@pytest.mark.asyncio
async def test_classify_and_diff_skips_orphan_only_existing_dataset():
    """Existing dataset with no baseline (all schemas orphan) → not in to_version;
    DiffPayload entry has current_version_num=None.
    """
    ds_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    cache = _Cache({uuid.uuid4(): "integer"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): []},
        schemas_by_ds={str(ds_id): [_model(id=v1_id, version_num=1)]},
        bindings_by_schema={str(v1_id): []},
        trees_by_ti={},
    )

    nd = _nd("target.demo.t", [_nf("id", "integer")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, to_version, payload = await classify_and_diff(
        client, SYSTEM_ID, normalized, cache
    )
    assert to_version == []
    assert payload.existing_datasets_diff[0]["current_version_num"] is None
```

Also update every existing `await classify_and_diff(...)` call in `crawler/tests/test_differ.py` to unpack three values. Search-and-replace these patterns:

- `_, payload = await classify_and_diff(` → `_, _, payload = await classify_and_diff(`
- `to_apply, payload = await classify_and_diff(` → `to_apply, _, payload = await classify_and_diff(`

(There are exactly these two call patterns in the existing file — verify via `grep -n "classify_and_diff" crawler/tests/test_differ.py`.)

- [ ] **Step 2.2: Run new tests to confirm they fail**

Run:

```bash
cd crawler && uv run pytest tests/test_differ.py -v
```

Expected: the 6 new plan tests FAIL with `ImportError` (can't import `VersionedDatasetPlan`) or `ValueError: too many values to unpack`. The existing tests you updated now unpack 3-tuple — they currently FAIL because the production code still returns a 2-tuple. That is expected; they go green after step 2.3.

- [ ] **Step 2.3: Implement plan dataclasses and extend `classify_and_diff`**

Edit `crawler/aide_crawler/differ.py`.

At the top (after the existing `@dataclass class DiffPayload` block, around line 46), add:

```python
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
```

Import `NormalizedField` at the top of the file — the existing `from aide_crawler.normalizer import NormalizedDataset, NormalizedResult` line becomes:

```python
from aide_crawler.normalizer import NormalizedDataset, NormalizedField, NormalizedResult
```

Replace the entire body of `classify_and_diff` (lines 172–261) with:

```python
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
        else:
            current_version_num = None  # orphan-only state

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
```

- [ ] **Step 2.4: Update runner to unpack 3-tuple**

Edit `crawler/aide_crawler/runner.py`. Find the call at line 99:

```python
            to_apply, payload = await classify_and_diff(
                client, system_id, normalized, type_cache
            )
```

Replace with:

```python
            to_apply, to_version, payload = await classify_and_diff(
                client, system_id, normalized, type_cache
            )
            # to_version wired in Task 4; ignored here to keep Task 2 focused.
            del to_version
```

- [ ] **Step 2.5: Update existing runner tests to unpack 3-tuple**

In `crawler/tests/test_runner.py`, find the monkeypatch call:

```python
    monkeypatch.setattr(
        "aide_crawler.runner.classify_and_diff",
        AsyncMock(return_value=([], DiffPayload())),
    )
```

Replace with:

```python
    monkeypatch.setattr(
        "aide_crawler.runner.classify_and_diff",
        AsyncMock(return_value=([], [], DiffPayload())),
    )
```

- [ ] **Step 2.6: Run full crawler test suite to confirm PASS**

Run:

```bash
cd crawler && uv run pytest tests/ -v
```

Expected: all tests pass, including the 6 new plan tests and the updated existing differ/runner tests.

- [ ] **Step 2.7: Run format + lint**

Run:

```bash
make format && make check
```

Expected: no errors.

- [ ] **Step 2.8: Commit**

```bash
git add crawler/aide_crawler/differ.py crawler/aide_crawler/runner.py crawler/tests/test_differ.py crawler/tests/test_runner.py
git commit -m "feat(crawler): emit VersionedDatasetPlan from classify_and_diff

Differ now returns (to_apply, to_version, payload). Each plan carries
current/next version numbers, the post-change field list, snapshots of
unchanged field bindings to reuse, and the split of added/type-changed/
removed fields. Runner unpacks the third slot but does not use it yet;
applier wiring lands in a follow-up."
```

---

## Task 3: Add `apply_versioned_datasets` in applier

**Files:**
- Modify: `crawler/aide_crawler/applier.py` (add new dataclass + function at end of file, after `apply_new_datasets`)
- Test: `crawler/tests/test_applier.py`

**What this does:** Implements the per-plan 3-call pattern: POST `/dataset-schemas/` → POST `/fields/batch` (added fields only) → POST `/type-instances/batch` (added + type-changed) → POST `/field-bindings/batch` (full set for new version, reusing unchanged type_instance_ids).

- [ ] **Step 3.1: Write failing tests for `apply_versioned_datasets`**

Append to `crawler/tests/test_applier.py`:

```python
# ---------------------------------------------------------------------------
# apply_versioned_datasets
# ---------------------------------------------------------------------------


def _snapshot(field_id: uuid.UUID, ti_id: uuid.UUID):
    """Build a FieldBindingSnapshot for test fixtures."""
    from aide_crawler.differ import FieldBindingSnapshot

    return FieldBindingSnapshot(field_id=field_id, type_instance_id=ti_id)


def _plan(
    *,
    dataset_id: uuid.UUID,
    object_name: str = "public.orders",
    current_version_num: int = 1,
    next_version_num: int = 2,
    all_fields: list,
    unchanged: dict | None = None,
    added: list | None = None,
    type_changed: list | None = None,
    removed_ids: list | None = None,
):
    from aide_crawler.differ import VersionedDatasetPlan

    return VersionedDatasetPlan(
        dataset_id=dataset_id,
        object_name=object_name,
        current_version_num=current_version_num,
        next_version_num=next_version_num,
        all_fields=all_fields,
        unchanged_field_bindings=unchanged or {},
        added_fields=added or [],
        type_changed_fields=type_changed or [],
        removed_field_ids=removed_ids or [],
    )


@pytest.mark.asyncio
async def test_versioned_apply_posts_schema_with_next_version_num():
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    fields = [_nf("id", position=0)]
    plan = _plan(
        dataset_id=ds_id,
        current_version_num=1,
        next_version_num=2,
        all_fields=fields,
        unchanged={"id": _snapshot(keep_id, keep_ti)},
    )
    client = _mock_client()
    cache = _Cache(["bigint"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    client.dataset_schemas.create.assert_awaited_once()
    created_arg = client.dataset_schemas.create.await_args.args[0]
    assert created_arg.dataset_id == ds_id
    assert created_arg.version_num == 2


@pytest.mark.asyncio
async def test_versioned_apply_allocates_version_skipping_orphans():
    """next_version_num=3 (baseline v1, orphan v2) → POSTs v3, not v2."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    fields = [_nf("id", position=0)]
    plan = _plan(
        dataset_id=ds_id,
        current_version_num=1,
        next_version_num=3,
        all_fields=fields,
        unchanged={"id": _snapshot(keep_id, keep_ti)},
    )
    client = _mock_client()
    cache = _Cache(["bigint"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    created_arg = client.dataset_schemas.create.await_args.args[0]
    assert created_arg.version_num == 3


@pytest.mark.asyncio
async def test_versioned_apply_reuses_unchanged_type_instance():
    """Unchanged fields → binding cites existing type_instance_id; no new TI posts."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    id_field = uuid.uuid4()
    total_field = uuid.uuid4()
    id_ti = uuid.uuid4()
    total_ti = uuid.uuid4()
    schema_id = uuid.uuid4()
    fields = [_nf("id", position=0), _nf("total", position=1)]
    plan = _plan(
        dataset_id=ds_id,
        all_fields=fields,
        unchanged={
            "id": _snapshot(id_field, id_ti),
            "total": _snapshot(total_field, total_ti),
        },
    )

    client = _mock_client()
    client.dataset_schemas.create = AsyncMock(return_value=_obj(id=schema_id))
    cache = _Cache(["bigint"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    # No TypeInstance creation — nothing changed.
    client.type_instances.create_many.assert_not_called()
    client.type_instances.create.assert_not_called()
    # No field creation — nothing added.
    client.fields.create_many.assert_not_called()
    # One binding batch with both fields pointing at existing TIs.
    client.field_bindings.create_many.assert_awaited_once()
    items = client.field_bindings.create_many.await_args.args[0]
    assert len(items) == 2
    by_field = {i.field_id: i for i in items}
    assert by_field[id_field].type_instance_id == id_ti
    assert by_field[id_field].dataset_schema_id == schema_id
    assert by_field[id_field].position == 0
    assert by_field[total_field].type_instance_id == total_ti
    assert by_field[total_field].position == 1


@pytest.mark.asyncio
async def test_versioned_apply_creates_fields_and_trees_for_added():
    """Added field → fields.create_many called; TI batch creates a new tree."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    schema_id = uuid.uuid4()
    new_field_id = uuid.uuid4()
    new_ti_id = uuid.uuid4()

    all_fields = [_nf("id", position=0), _nf("email", code="text", position=1)]
    added = [_nf("email", code="text", position=1)]
    plan = _plan(
        dataset_id=ds_id,
        all_fields=all_fields,
        unchanged={"id": _snapshot(keep_id, keep_ti)},
        added=added,
    )

    client = _mock_client()
    client.dataset_schemas.create = AsyncMock(return_value=_obj(id=schema_id))
    client.fields.create_many = AsyncMock(
        return_value=[_obj(id=new_field_id, name="email")]
    )
    client.type_instances.create_many = AsyncMock(return_value=[_obj(id=new_ti_id)])
    cache = _Cache(["bigint", "text"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    # Field create_many called once with exactly one added field
    client.fields.create_many.assert_awaited_once()
    created_fields_arg = client.fields.create_many.await_args.args[0]
    assert len(created_fields_arg) == 1
    assert created_fields_arg[0].name == "email"
    assert created_fields_arg[0].dataset_id == ds_id

    # Type instance batch called; depth 0 only for a flat "text" node
    assert client.type_instances.create_many.await_count == 1

    # Bindings batch has 2 entries; email points to new TI
    client.field_bindings.create_many.assert_awaited_once()
    items = client.field_bindings.create_many.await_args.args[0]
    by_field = {i.field_id: i for i in items}
    assert by_field[keep_id].type_instance_id == keep_ti
    assert by_field[new_field_id].type_instance_id == new_ti_id
    assert by_field[new_field_id].position == 1


@pytest.mark.asyncio
async def test_versioned_apply_rebuilds_tree_for_type_changes():
    """Type-changed field → new TypeInstance; binding uses new TI (not old)."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    field_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    new_ti_id = uuid.uuid4()

    changed_nf = _nf("n", code="bigint", position=0)
    plan = _plan(
        dataset_id=ds_id,
        all_fields=[changed_nf],
        unchanged={},
        type_changed=[changed_nf],
    )
    # Feed in the pre-existing field_id via a helper: the plan's type_changed
    # field references the same NormalizedField, but the applier must know
    # the Field row already exists. We convey this via a small extension:
    # type_changed fields' existing field_ids come from a separate dict on
    # the plan. The applier fetches {name: field_id} for the dataset.
    client = _mock_client(fields_map={"n": field_id})
    client.dataset_schemas.create = AsyncMock(return_value=_obj(id=schema_id))
    client.type_instances.create_many = AsyncMock(return_value=[_obj(id=new_ti_id)])
    cache = _Cache(["bigint"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    # No new Field row for a type-changed column.
    client.fields.create_many.assert_not_called()
    # One TI batch call for the one type-changed field.
    assert client.type_instances.create_many.await_count == 1
    # Binding points to the new TI.
    client.field_bindings.create_many.assert_awaited_once()
    items = client.field_bindings.create_many.await_args.args[0]
    assert len(items) == 1
    assert items[0].field_id == field_id
    assert items[0].type_instance_id == new_ti_id


@pytest.mark.asyncio
async def test_versioned_apply_omits_removed_fields():
    """removed_field_ids are not in the new binding set (no binding row for them)."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    drop_id = uuid.uuid4()
    schema_id = uuid.uuid4()

    plan = _plan(
        dataset_id=ds_id,
        all_fields=[_nf("id", position=0)],
        unchanged={"id": _snapshot(keep_id, keep_ti)},
        removed_ids=[drop_id],
    )
    client = _mock_client()
    client.dataset_schemas.create = AsyncMock(return_value=_obj(id=schema_id))
    cache = _Cache(["bigint"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    items = client.field_bindings.create_many.await_args.args[0]
    field_ids_in_bindings = {i.field_id for i in items}
    assert drop_id not in field_ids_in_bindings


@pytest.mark.asyncio
async def test_versioned_apply_409_reraises():
    """Unique (dataset_id, version_num) collision → exception propagates."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    plan = _plan(
        dataset_id=ds_id,
        all_fields=[_nf("id", position=0)],
        unchanged={"id": _snapshot(keep_id, keep_ti)},
    )

    class _Conflict(Exception):
        pass

    client = _mock_client()
    client.dataset_schemas.create = AsyncMock(side_effect=_Conflict("409"))
    cache = _Cache(["bigint"])

    with pytest.raises(_Conflict):
        await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    # No downstream calls after schema POST failed
    client.fields.create_many.assert_not_called()
    client.type_instances.create_many.assert_not_called()
    client.field_bindings.create_many.assert_not_called()


@pytest.mark.asyncio
async def test_versioned_apply_returns_result_records():
    """Return value: one VersionedDataset per plan with the new schema id + version."""
    from aide_crawler.applier import VersionedDataset, apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    new_schema_id = uuid.uuid4()

    plan = _plan(
        dataset_id=ds_id,
        object_name="public.orders",
        current_version_num=1,
        next_version_num=2,
        all_fields=[_nf("id", position=0)],
        unchanged={"id": _snapshot(keep_id, keep_ti)},
    )
    client = _mock_client()
    client.dataset_schemas.create = AsyncMock(return_value=_obj(id=new_schema_id))
    cache = _Cache(["bigint"])

    results = await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, VersionedDataset)
    assert r.dataset_id == ds_id
    assert r.object_name == "public.orders"
    assert r.old_version_num == 1
    assert r.new_version_num == 2
    assert r.dataset_schema_id == new_schema_id
    assert r.fields_added == 0
    assert r.fields_removed == 0
    assert r.type_changes == 0
```

- [ ] **Step 3.2: Run new tests to confirm they fail**

Run:

```bash
cd crawler && uv run pytest tests/test_applier.py -v -k versioned
```

Expected: all 8 new tests FAIL with `ImportError` (cannot import `apply_versioned_datasets` / `VersionedDataset`).

- [ ] **Step 3.3: Implement `VersionedDataset` result + `apply_versioned_datasets`**

Edit `crawler/aide_crawler/applier.py`. After the existing `AppliedDataset` dataclass (around line 24), add:

```python
@dataclass
class VersionedDataset:
    """Return record for apply_versioned_datasets — one per plan."""

    dataset_id: uuid.UUID
    object_name: str
    dataset_schema_id: uuid.UUID
    old_version_num: int
    new_version_num: int
    fields_added: int
    fields_removed: int
    type_changes: int
```

Append at the very end of `crawler/aide_crawler/applier.py` (after `apply_new_datasets` returns, line 275):

```python
async def apply_versioned_datasets(
    client,
    *,
    plans: list,  # list[VersionedDatasetPlan] — avoid circular import in annotation
    type_cache: TypeCache,
) -> list[VersionedDataset]:
    """Create a new DatasetSchema version per plan, with full FieldBinding set.

    For each plan:
      1. POST /dataset-schemas/ with version_num = plan.next_version_num.
      2. POST /fields/batch for added fields (Field rows are dataset-level).
      3. POST /type-instances/batch for added + type-changed fields (one
         per-depth batch handled by _batch_create_type_trees).
      4. POST /field-bindings/batch with one entry per field in
         plan.all_fields; unchanged fields reuse the existing
         type_instance_id from plan.unchanged_field_bindings.

    Failures on any step propagate — matches apply_new_datasets policy.
    A partial-failure run leaves an orphan DatasetSchema row, which the
    differ filters out via the non-orphan baseline rule on the next crawl.
    """
    results: list[VersionedDataset] = []

    for plan in plans:
        # --- 1. New DatasetSchema row ---
        new_schema = await client.dataset_schemas.create(
            DatasetSchemaCreate(  # type: ignore[call-arg]
                dataset_id=plan.dataset_id,
                version_num=plan.next_version_num,
            )
        )
        new_schema_id = new_schema.id

        # --- 2. New Field rows (added fields only) ---
        field_ids_by_name: dict[str, uuid.UUID] = {
            name: snap.field_id
            for name, snap in plan.unchanged_field_bindings.items()
        }
        if plan.added_fields:
            created_fields = await client.fields.create_many(
                [
                    FieldCreate(  # type: ignore[call-arg]
                        dataset_id=plan.dataset_id,
                        name=nf.name,
                        path=nf.path,
                    )
                    for nf in plan.added_fields
                ]
            )
            for cf in created_fields:
                field_ids_by_name[cf.name] = cf.id

        # --- 3. TypeInstance trees for added + type-changed fields ---
        fields_needing_trees = plan.added_fields + plan.type_changed_fields
        if fields_needing_trees:
            # Type-changed fields use their existing Field row (not in the
            # created_fields batch). Look up field_id by name — it lives in
            # the metastore already, so fetch it.
            type_changed_names = {nf.name for nf in plan.type_changed_fields}
            if type_changed_names:
                all_field_rows = await _list_fields_map(
                    client, dataset_id=plan.dataset_id
                )
                for name in type_changed_names:
                    if name not in field_ids_by_name:
                        field_ids_by_name[name] = all_field_rows[name]
            field_root_nodes: list[tuple[uuid.UUID, TypeNode]] = [
                (field_ids_by_name[nf.name], nf.type_node)
                for nf in fields_needing_trees
            ]
            new_ti_by_field = await _batch_create_type_trees(
                client, field_root_nodes=field_root_nodes, type_cache=type_cache
            )
        else:
            new_ti_by_field = {}

        # --- 4. Full FieldBinding set for the new version ---
        bindings_to_create: list[FieldBindingCreate] = []
        for idx, nf in enumerate(plan.all_fields):
            snap = plan.unchanged_field_bindings.get(nf.name)
            if snap is not None:
                field_id = snap.field_id
                type_instance_id = snap.type_instance_id
            else:
                field_id = field_ids_by_name[nf.name]
                type_instance_id = new_ti_by_field[field_id]
            bindings_to_create.append(
                FieldBindingCreate(  # type: ignore[call-arg]
                    field_id=field_id,
                    dataset_schema_id=new_schema_id,
                    type_instance_id=type_instance_id,
                    position=idx,
                    is_nullable=nf.nullable,
                )
            )
        if bindings_to_create:
            await client.field_bindings.create_many(bindings_to_create)

        results.append(
            VersionedDataset(
                dataset_id=plan.dataset_id,
                object_name=plan.object_name,
                dataset_schema_id=new_schema_id,
                old_version_num=plan.current_version_num,
                new_version_num=plan.next_version_num,
                fields_added=len(plan.added_fields),
                fields_removed=len(plan.removed_field_ids),
                type_changes=len(plan.type_changed_fields),
            )
        )

    return results
```

- [ ] **Step 3.4: Run full applier test suite to confirm PASS**

Run:

```bash
cd crawler && uv run pytest tests/test_applier.py -v
```

Expected: every test passes, including the 8 new versioned-apply tests and the pre-existing `apply_new_datasets` tests (unchanged).

- [ ] **Step 3.5: Run format + lint**

Run:

```bash
make format && make check
```

Expected: no errors.

- [ ] **Step 3.6: Commit**

```bash
git add crawler/aide_crawler/applier.py crawler/tests/test_applier.py
git commit -m "feat(crawler): add apply_versioned_datasets

Creates DatasetSchema v{next}, new Field rows for added columns, new
TypeInstance trees for added + type-changed columns, and a full
FieldBinding set that reuses unchanged fields' TypeInstance IDs verbatim.
Orphan-safe: next_version_num is max(version_num)+1 across all rows,
caller decides the allocation. Failures re-raise; partial state is
filtered out by the differ on the next crawl."
```

---

## Task 4: Wire `apply_versioned_datasets` into the runner

**Files:**
- Modify: `crawler/aide_crawler/runner.py`
- Test: `crawler/tests/test_runner.py`

**What this does:** Calls `apply_versioned_datasets` after `apply_new_datasets`, fills `new_version_num` into the per-dataset `DiffPayload` entries, extends the `crawl_runs.summary` with `new_versions_created` and a `versioned_datasets` list, and logs a warning when an existing dataset has no baseline (orphan-only case).

- [ ] **Step 4.1: Write failing tests for runner wiring**

Append to `crawler/tests/test_runner.py`:

```python
@pytest.mark.asyncio
async def test_runner_calls_versioned_apply_when_to_version_nonempty(monkeypatch):
    """to_version non-empty → apply_versioned_datasets called; summary extended."""
    system_id = uuid.uuid4()
    flavor_id = uuid.uuid4()
    crawl_run_id = uuid.uuid4()
    ds_id = uuid.uuid4()
    new_schema_id = uuid.uuid4()

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    client.systems = AsyncMock()
    client.systems.list = AsyncMock(
        return_value=_page([_obj(id=system_id, flavor_id=flavor_id)], total=1)
    )
    client.data_types = AsyncMock()
    client.data_types.list = AsyncMock(
        side_effect=[
            _page([_obj(id=uuid.uuid4(), code="bigint", params_schema={})], total=1),
            _page(
                [_obj(id=uuid.uuid4(), code="bigint", params_schema={})],
                pages=1,
                total=1,
            ),
        ]
    )
    client.crawl_runs = AsyncMock()
    client.crawl_runs.create = AsyncMock(
        return_value=_obj(id=crawl_run_id, row_version=0)
    )
    client.crawl_runs.update = AsyncMock()

    from aide_crawler.applier import VersionedDataset
    from aide_crawler.differ import DiffPayload, VersionedDatasetPlan

    plan = VersionedDatasetPlan(
        dataset_id=ds_id,
        object_name="public.orders",
        current_version_num=1,
        next_version_num=2,
        all_fields=[],
        unchanged_field_bindings={},
        added_fields=[],
        type_changed_fields=[],
        removed_field_ids=[],
    )
    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "public.orders",
                "dataset_id": str(ds_id),
                "current_version_num": 1,
                "new_version_num": None,
                "new_fields": [{"name": "status", "code": "varchar", "params": {}}],
                "removed_fields": [],
                "type_changes": [],
            }
        ]
    )

    monkeypatch.setattr(
        "aide_crawler.runner.run_inspection",
        lambda *a, **k: _obj(dialect_name="postgresql", tables=[]),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.normalize",
        lambda _: _obj(dialect_name="postgresql", datasets=[]),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.classify_and_diff",
        AsyncMock(return_value=([], [plan], payload)),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.apply_new_datasets", AsyncMock(return_value=[])
    )
    versioned_result = [
        VersionedDataset(
            dataset_id=ds_id,
            object_name="public.orders",
            dataset_schema_id=new_schema_id,
            old_version_num=1,
            new_version_num=2,
            fields_added=1,
            fields_removed=0,
            type_changes=0,
        )
    ]
    apply_versioned_mock = AsyncMock(return_value=versioned_result)
    monkeypatch.setattr(
        "aide_crawler.runner.apply_versioned_datasets", apply_versioned_mock
    )
    monkeypatch.setattr("aide_crawler.runner.format_report", lambda *a, **k: None)

    with patch("aide_crawler.runner.AideClient", return_value=client):
        await run_crawl(
            system_code="sys",
            connection_url="postgresql://x",
            metastore_url="http://m",
            metastore_user="u",
            metastore_password="p",
        )

    apply_versioned_mock.assert_awaited_once()
    call_kwargs = apply_versioned_mock.await_args.kwargs
    assert call_kwargs["plans"] == [plan]

    update_args, _ = client.crawl_runs.update.await_args
    update_payload = update_args[1]
    assert update_payload.status.value == "completed"
    assert update_payload.summary["new_versions_created"] == 1
    assert len(update_payload.summary["versioned_datasets"]) == 1
    vd_entry = update_payload.summary["versioned_datasets"][0]
    assert vd_entry["object_name"] == "public.orders"
    assert vd_entry["old_version"] == 1
    assert vd_entry["new_version"] == 2
    assert vd_entry["added"] == 1
    # DiffPayload entry's new_version_num is filled in post-apply
    diff_entry = update_payload.diff_payload["existing_datasets_diff"][0]
    assert diff_entry["new_version_num"] == 2


@pytest.mark.asyncio
async def test_runner_skips_versioned_apply_when_to_version_empty(monkeypatch):
    """Empty to_version → apply_versioned_datasets called with empty list;
    summary shows new_versions_created=0."""
    system_id = uuid.uuid4()
    flavor_id = uuid.uuid4()
    crawl_run_id = uuid.uuid4()

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    client.systems = AsyncMock()
    client.systems.list = AsyncMock(
        return_value=_page([_obj(id=system_id, flavor_id=flavor_id)], total=1)
    )
    client.data_types = AsyncMock()
    client.data_types.list = AsyncMock(
        side_effect=[
            _page([_obj(id=uuid.uuid4(), code="bigint", params_schema={})], total=1),
            _page(
                [_obj(id=uuid.uuid4(), code="bigint", params_schema={})],
                pages=1,
                total=1,
            ),
        ]
    )
    client.crawl_runs = AsyncMock()
    client.crawl_runs.create = AsyncMock(
        return_value=_obj(id=crawl_run_id, row_version=0)
    )
    client.crawl_runs.update = AsyncMock()

    from aide_crawler.differ import DiffPayload

    monkeypatch.setattr(
        "aide_crawler.runner.run_inspection",
        lambda *a, **k: _obj(dialect_name="postgresql", tables=[]),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.normalize",
        lambda _: _obj(dialect_name="postgresql", datasets=[]),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.classify_and_diff",
        AsyncMock(return_value=([], [], DiffPayload())),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.apply_new_datasets", AsyncMock(return_value=[])
    )
    apply_versioned_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "aide_crawler.runner.apply_versioned_datasets", apply_versioned_mock
    )
    monkeypatch.setattr("aide_crawler.runner.format_report", lambda *a, **k: None)

    with patch("aide_crawler.runner.AideClient", return_value=client):
        await run_crawl(
            system_code="sys",
            connection_url="postgresql://x",
            metastore_url="http://m",
            metastore_user="u",
            metastore_password="p",
        )

    update_args, _ = client.crawl_runs.update.await_args
    update_payload = update_args[1]
    assert update_payload.summary["new_versions_created"] == 0
    assert update_payload.summary["versioned_datasets"] == []


@pytest.mark.asyncio
async def test_runner_warns_on_orphan_only_existing_dataset(
    monkeypatch, caplog
):
    """DiffPayload entry with current_version_num=None → runner logs a warning."""
    import logging

    system_id = uuid.uuid4()
    flavor_id = uuid.uuid4()
    crawl_run_id = uuid.uuid4()

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    client.systems = AsyncMock()
    client.systems.list = AsyncMock(
        return_value=_page([_obj(id=system_id, flavor_id=flavor_id)], total=1)
    )
    client.data_types = AsyncMock()
    client.data_types.list = AsyncMock(
        side_effect=[
            _page([_obj(id=uuid.uuid4(), code="bigint", params_schema={})], total=1),
            _page(
                [_obj(id=uuid.uuid4(), code="bigint", params_schema={})],
                pages=1,
                total=1,
            ),
        ]
    )
    client.crawl_runs = AsyncMock()
    client.crawl_runs.create = AsyncMock(
        return_value=_obj(id=crawl_run_id, row_version=0)
    )
    client.crawl_runs.update = AsyncMock()

    from aide_crawler.differ import DiffPayload

    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "public.orphan",
                "dataset_id": str(uuid.uuid4()),
                "current_version_num": None,
                "new_version_num": None,
                "new_fields": [],
                "removed_fields": [],
                "type_changes": [],
            }
        ]
    )
    monkeypatch.setattr(
        "aide_crawler.runner.run_inspection",
        lambda *a, **k: _obj(dialect_name="postgresql", tables=[]),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.normalize",
        lambda _: _obj(dialect_name="postgresql", datasets=[]),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.classify_and_diff",
        AsyncMock(return_value=([], [], payload)),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.apply_new_datasets", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "aide_crawler.runner.apply_versioned_datasets",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr("aide_crawler.runner.format_report", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING, logger="aide_crawler.runner"):
        with patch("aide_crawler.runner.AideClient", return_value=client):
            await run_crawl(
                system_code="sys",
                connection_url="postgresql://x",
                metastore_url="http://m",
                metastore_user="u",
                metastore_password="p",
            )

    assert any("public.orphan" in rec.message for rec in caplog.records)
    assert any("orphan" in rec.message.lower() for rec in caplog.records)
```

- [ ] **Step 4.2: Run new tests to confirm they fail**

Run:

```bash
cd crawler && uv run pytest tests/test_runner.py -v -k "versioned_apply or orphan_only"
```

Expected: all 3 new tests FAIL. The first two fail with `AttributeError` / `AssertionError` because `apply_versioned_datasets` isn't imported or called in the runner yet. The orphan-warn test fails because there is no warning log yet.

- [ ] **Step 4.3: Implement runner changes**

Edit `crawler/aide_crawler/runner.py`. Imports at top — add `logging` and wire new helpers:

```python
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from aide_schemas.crawl_run import CrawlRunCreate, CrawlRunUpdate, CrawlStatus
from aide_sdk import AideClient

from aide_crawler.applier import apply_new_datasets, apply_versioned_datasets
from aide_crawler.differ import classify_and_diff
from aide_crawler.inspector import run_inspection
from aide_crawler.normalizer import normalize
from aide_crawler.reporter import format_report
from aide_crawler.type_cache import TypeCache

logger = logging.getLogger(__name__)
```

Replace the whole try/except block inside `run_crawl` (lines 88–146) with:

```python
        try:
            inspection = run_inspection(
                connection_url,
                include_schemas=include_schemas,
                exclude_schemas=exclude_schemas,
                include_tables=include_tables,
                exclude_tables=exclude_tables,
            )

            normalized = normalize(inspection)

            to_apply, to_version, payload = await classify_and_diff(
                client, system_id, normalized, type_cache
            )

            # Warn on orphan-only existing datasets (no baseline schema version).
            for entry in payload.existing_datasets_diff:
                if entry.get("current_version_num") is None:
                    logger.warning(
                        "Dataset '%s' has no baseline DatasetSchema with bindings; "
                        "skipping versioned apply (orphan-only state).",
                        entry["object_name"],
                    )

            applied = await apply_new_datasets(
                client,
                system_id=system_id,
                datasets=to_apply,
                type_cache=type_cache,
            )
            payload.new_datasets_applied = [
                {
                    "object_name": a.object_name,
                    "dataset_id": str(a.dataset_id),
                    "fields_count": a.fields_count,
                }
                for a in applied
            ]

            versioned = await apply_versioned_datasets(
                client, plans=to_version, type_cache=type_cache
            )
            # Fill new_version_num back into the DiffPayload entries.
            by_ds_id = {str(v.dataset_id): v for v in versioned}
            for entry in payload.existing_datasets_diff:
                v = by_ds_id.get(entry["dataset_id"])
                if v is not None:
                    entry["new_version_num"] = v.new_version_num

            if output_file:
                with open(output_file, "w") as f:
                    format_report(payload, output_format, f)
                print(f"Report written to {output_file}", file=sys.stderr)
            else:
                format_report(payload, output_format)

            summary = {
                **payload.counts(),
                "new_versions_created": len(versioned),
                "versioned_datasets": [
                    {
                        "dataset_id": str(v.dataset_id),
                        "object_name": v.object_name,
                        "old_version": v.old_version_num,
                        "new_version": v.new_version_num,
                        "added": v.fields_added,
                        "removed": v.fields_removed,
                        "type_changes": v.type_changes,
                    }
                    for v in versioned
                ],
            }

            await client.crawl_runs.update(
                crawl_run.id,
                CrawlRunUpdate(
                    status=CrawlStatus.COMPLETED,
                    finished_at=datetime.now(timezone.utc),
                    summary=summary,
                    diff_payload=payload.to_dict(),
                    row_version=crawl_run.row_version,
                ),
            )

        except Exception as exc:
            await client.crawl_runs.update(
                crawl_run.id,
                CrawlRunUpdate(
                    status=CrawlStatus.FAILED,
                    finished_at=datetime.now(timezone.utc),
                    error_message=str(exc),
                    row_version=crawl_run.row_version,
                ),
            )
            raise
```

Also remove the now-dead lines from the Task 2 stub:

```python
            # to_version wired in Task 4; ignored here to keep Task 2 focused.
            del to_version
```

(They are superseded by the block above.)

- [ ] **Step 4.4: Run full runner test suite to confirm PASS**

Run:

```bash
cd crawler && uv run pytest tests/test_runner.py -v
```

Expected: all tests pass — the 3 new tests, plus the pre-existing happy-path / SystemExit / failure tests (which still use the monkeypatched `classify_and_diff` that now returns a 3-tuple, updated in Task 2).

- [ ] **Step 4.5: Run entire crawler suite to check nothing regressed**

Run:

```bash
cd crawler && uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4.6: Run format + lint**

Run:

```bash
make format && make check
```

Expected: no errors.

- [ ] **Step 4.7: Commit**

```bash
git add crawler/aide_crawler/runner.py crawler/tests/test_runner.py
git commit -m "feat(crawler): runner calls apply_versioned_datasets on diff

After apply_new_datasets, runner now invokes apply_versioned_datasets
with the plan list from the differ. Fills new_version_num back into
diff_payload entries, extends crawl_runs.summary with new_versions_created
and a versioned_datasets array. Orphan-only existing datasets (no baseline)
are logged as warnings and skipped — pathological state, no auto-recovery
in v1."
```

---

## Task 5: Extend reporter with versioned datasets section

**Files:**
- Modify: `crawler/aide_crawler/reporter.py`
- Test: `crawler/tests/test_reporter.py`

**What this does:** Adds a "Versioned datasets" section to the text report. JSON report already reflects the new `current_version_num` / `new_version_num` keys via `DiffPayload.to_dict()` — verify with a test.

- [ ] **Step 5.1: Write failing tests for reporter changes**

Append to `crawler/tests/test_reporter.py`:

```python
def test_report_text_versioned_datasets_section():
    """Existing dataset that got a new version → 'v1 -> v2' line + counts."""
    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "public.orders",
                "dataset_id": "xyz",
                "current_version_num": 1,
                "new_version_num": 2,
                "new_fields": [{"name": "status", "code": "varchar", "params": {}}],
                "removed_fields": [{"name": "legacy", "field_id": "f1"}],
                "type_changes": [
                    {
                        "field_name": "amount",
                        "field_id": "f2",
                        "before": {"code": "numeric", "params": {}},
                        "after": {"code": "bigint", "params": {}},
                    }
                ],
            }
        ]
    )
    buf = StringIO()
    report_text(payload, buf)
    out = buf.getvalue()
    assert "Versioned" in out
    assert "public.orders" in out
    assert "v1" in out and "v2" in out
    assert "+1" in out
    assert "-1" in out
    assert "~1" in out


def test_report_text_skips_versioned_section_when_no_versioned():
    """Existing datasets with current_version_num=None (orphan) or no diff → no
    versioned section header should appear."""
    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "public.orphan",
                "dataset_id": "a",
                "current_version_num": None,
                "new_version_num": None,
                "new_fields": [],
                "removed_fields": [],
                "type_changes": [],
            }
        ]
    )
    buf = StringIO()
    report_text(payload, buf)
    assert "Versioned Datasets" not in buf.getvalue()


def test_report_text_lists_only_datasets_with_new_version():
    """Datasets without new_version_num (e.g. unchanged) are not in versioned section."""
    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "public.unchanged",
                "dataset_id": "u",
                "current_version_num": 1,
                "new_version_num": None,
                "new_fields": [],
                "removed_fields": [],
                "type_changes": [],
            },
            {
                "object_name": "public.changed",
                "dataset_id": "c",
                "current_version_num": 1,
                "new_version_num": 2,
                "new_fields": [{"name": "x", "code": "text", "params": {}}],
                "removed_fields": [],
                "type_changes": [],
            },
        ]
    )
    buf = StringIO()
    report_text(payload, buf)
    out = buf.getvalue()
    assert "public.changed" in out
    # The versioned SECTION should mention changed only. Assert by checking that
    # the 'v1 -> v2' line appears for changed and not for unchanged.
    versioned_section_start = out.find("Versioned Datasets")
    assert versioned_section_start >= 0
    section = out[versioned_section_start:]
    assert "public.changed" in section
    assert "public.unchanged" not in section


def test_report_json_carries_new_version_num():
    """JSON output reflects new_version_num via DiffPayload.to_dict()."""
    import json as _json

    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "public.orders",
                "dataset_id": "xyz",
                "current_version_num": 1,
                "new_version_num": 2,
                "new_fields": [],
                "removed_fields": [],
                "type_changes": [],
            }
        ]
    )
    buf = StringIO()
    report_json(payload, buf)
    data = _json.loads(buf.getvalue())
    entry = data["existing_datasets_diff"][0]
    assert entry["current_version_num"] == 1
    assert entry["new_version_num"] == 2
```

- [ ] **Step 5.2: Run new tests to confirm they fail**

Run:

```bash
cd crawler && uv run pytest tests/test_reporter.py -v -k "versioned or new_version_num"
```

Expected: `test_report_text_versioned_datasets_section`, `test_report_text_lists_only_datasets_with_new_version` FAIL (no "Versioned" string). `test_report_text_skips_versioned_section_when_no_versioned` currently PASSES trivially. `test_report_json_carries_new_version_num` PASSES (the payload entries carry the field already).

- [ ] **Step 5.3: Implement reporter changes**

Edit `crawler/aide_crawler/reporter.py`. Replace the whole `report_text` function with:

```python
def report_text(payload: DiffPayload, out: IO[str] = sys.stdout) -> None:
    out.write("=== AIDE Crawler Report ===\n\n")

    if payload.new_datasets_applied:
        out.write(f"--- Applied ({len(payload.new_datasets_applied)}) ---\n")
        for d in payload.new_datasets_applied:
            out.write(f"  Applied: {d['object_name']}  [{d['fields_count']} fields]\n")
        out.write("\n")

    if payload.existing_datasets_diff:
        out.write(
            f"--- Existing datasets with changes "
            f"({len(payload.existing_datasets_diff)}) ---\n"
        )
        for entry in payload.existing_datasets_diff:
            out.write(f"  * {entry['object_name']}\n")
            for nf in entry["new_fields"]:
                out.write(f"      + {nf['name']} ({nf['code']})\n")
            for rf in entry["removed_fields"]:
                out.write(f"      - {rf['name']}\n")
            for change in entry.get("type_changes", []):
                before_str = _fmt_type(change.get("full_before") or change["before"])
                after_str = _fmt_type(change.get("full_after") or change["after"])
                out.write(
                    f"      ~ {change['field_name']}: {before_str} -> {after_str}\n"
                )
        out.write("\n")

    versioned_entries = [
        e
        for e in payload.existing_datasets_diff
        if e.get("new_version_num") is not None
    ]
    if versioned_entries:
        out.write(f"--- Versioned Datasets ({len(versioned_entries)}) ---\n")
        for entry in versioned_entries:
            added = len(entry.get("new_fields", []))
            removed = len(entry.get("removed_fields", []))
            tchg = len(entry.get("type_changes", []))
            out.write(
                f"  {entry['object_name']}  "
                f"v{entry['current_version_num']} -> v{entry['new_version_num']}  "
                f"+{added}/-{removed}/~{tchg}\n"
            )
        out.write("\n")

    if payload.removed_datasets:
        out.write(f"--- Removed datasets ({len(payload.removed_datasets)}) ---\n")
        for d in payload.removed_datasets:
            out.write(f"  - {d['object_name']}\n")
        out.write("\n")

    out.write("--- Summary ---\n")
    for k, v in payload.counts().items():
        out.write(f"  {k}: {v}\n")
```

- [ ] **Step 5.4: Run reporter tests to confirm PASS**

Run:

```bash
cd crawler && uv run pytest tests/test_reporter.py -v
```

Expected: all tests pass, including the 4 new reporter tests.

- [ ] **Step 5.5: Run entire crawler suite end-to-end**

Run:

```bash
cd crawler && uv run pytest tests/ -v
```

Expected: every test in the crawler package passes.

- [ ] **Step 5.6: Run format + lint**

Run:

```bash
make format && make check
```

Expected: no errors.

- [ ] **Step 5.7: Commit**

```bash
git add crawler/aide_crawler/reporter.py crawler/tests/test_reporter.py
git commit -m "feat(crawler): reporter shows versioned datasets section

Text report gains a '--- Versioned Datasets ---' block listing each
dataset that got a new schema version: 'name v{old} -> v{new} +a/-r/~t'.
JSON output unchanged (DiffPayload.to_dict already surfaces the version
fields). Datasets without new_version_num (unchanged or orphan-only)
are not listed in the versioned section."
```

---

## End-of-plan verification

- [ ] **Final step: Full test run + lint from repo root**

Run:

```bash
cd crawler && uv run pytest tests/ -v
make format && make check
```

Expected: all tests pass, no lint errors.

- [ ] **Manual smoke (optional, only if a local PG fixture is available):**

If you have a metastore and a source PG running, crawl twice: once to populate v1, then alter a column's type and add a column at the source and re-crawl. Inspect:

```sql
SELECT id, version_num FROM dataset_schemas WHERE dataset_id = '<orders_id>' ORDER BY version_num;
SELECT COUNT(*) FROM field_bindings WHERE dataset_schema_id = '<v2_id>';
```

Expected: two rows in `dataset_schemas`, one per version; `field_bindings` for v2 count = number of current source columns. Unchanged columns' bindings reuse the same `type_instance_id` as v1 — confirm with:

```sql
SELECT fb1.field_id, fb1.type_instance_id AS v1_ti, fb2.type_instance_id AS v2_ti
FROM field_bindings fb1
JOIN field_bindings fb2 ON fb1.field_id = fb2.field_id
WHERE fb1.dataset_schema_id = '<v1_id>' AND fb2.dataset_schema_id = '<v2_id>';
```

Unchanged rows have `v1_ti = v2_ti`; type-changed rows have `v1_ti != v2_ti`.
