# Crawler: Dataset Schema Versioning

Date: 2026-04-16
Status: Design approved

## Problem

Crawler today has two behaviours for an existing dataset:

1. If the dataset is absent in the metastore → create `Dataset`, `DatasetSchema v1`, `Field`s, `TypeInstance` trees, `FieldBinding`s.
2. If the dataset is present → compute a structured `DiffPayload` (new/removed fields, type changes) and persist it on `crawl_runs.diff_payload` — **nothing is written back**. The metastore's schema stays at v1 forever.

The data model already supports multi-version schemas: `DatasetSchema` has `(dataset_id, version_num)` unique key, `FieldBinding` pins a field to a specific `dataset_schema_id`, and `TypeInstance` trees are free-standing (can be shared across bindings). Batch creation is wired end-to-end for fields, type instances, and field bindings.

The gap is pure crawler wiring: the applier always creates / finds v1, the differ always picks v1 as the baseline, and the runner never triggers a versioned apply.

## Goals

1. On any structural diff for an existing dataset (added field, removed field, type change), the crawler creates a new `DatasetSchema` with `version_num = max_existing_version_num + 1` (covers prior orphans — see edge cases) and a full set of `FieldBinding`s for the current field set.
2. Unchanged fields in the new version reuse the existing `TypeInstance` tree (shared across versions). New `TypeInstance` trees are created only for added fields and fully-rebuilt for type-changed fields.
3. The differ picks the latest **non-orphan** schema version (at least one `FieldBinding` exists) as the baseline for the next diff. Subsequent crawls become idempotent once the source stops drifting.
4. `crawl_runs.diff_payload` is still populated (audit trail), augmented with the new `version_num` per versioned dataset.

## Non-goals

- Backend model, API, or schema changes. No new endpoints, no migrations, no `status` field on `DatasetSchema`, no `active_version_num` on `Dataset`.
- Atomic multi-step backend endpoint. Crawler keeps the existing 3-call pattern (schema → type-instances → bindings) per dataset.
- Active / published / draft state machine.
- Position reorder detection (differ doesn't currently track position changes).
- Rename detection (rename shows as add + remove, which is acceptable).
- Removed-dataset handling (dataset disappears at source).
- `DatasetSchema.schema` JSONB population (stays `NULL`).
- Orphan schema cleanup tool.
- Per-dataset failure isolation in the applier loop. Matches existing `apply_new_datasets` behaviour — a single raise aborts the whole apply phase and the crawl run is marked `FAILED`. Hardening is a separate concern.
- Nullable-only changes (detected by differ only via type change; standalone `is_nullable` flip without type change does not trigger a new version today).

## Architecture

```
crawler run (existing steps unchanged up to classify_and_diff)
  ├── classify_and_diff
  │     ├── for each existing dataset: pick latest non-orphan schema (was: hardcoded v1)
  │     └── emit DiffPayload + to_apply_new + to_version  ← NEW list
  ├── apply_new_datasets (unchanged)           — creates v1 for new datasets
  ├── apply_versioned_datasets (NEW)           — creates v{N+1} for diffed datasets
  └── crawl_runs.update(status, summary, diff_payload)
```

`apply_versioned_datasets` runs after `apply_new_datasets` and only touches datasets with a non-empty diff.

## Components

### Differ (`crawler/aide_crawler/differ.py`)

**Replace `_find_schema_v1_id` with two helpers:**

- `_find_baseline_schema(client, dataset_id)` → `(schema_id, version_num) | None`. Returns the **latest schema with at least one `FieldBinding`** — the baseline for diff computation. `None` if no such schema exists (treat as "dataset is new to crawler" and route through `apply_new_datasets`, not versioning; unusual but well-defined).
- `_find_max_version_num(client, dataset_id)` → `int`. Returns the **highest `version_num` across all rows including orphans**. Used only for next-version allocation. Distinct from the baseline because an orphan (partial-run remnant) sits above the baseline and must not be reused.

**`DiffPayload` per-dataset entries gain `current_version_num: int`** (the baseline used for the diff) and `new_version_num: int | None` (filled in by the applier once the new schema row is created). The payload envelope's own `schema_version` (DiffPayload format version) stays `1` and is unrelated.

**New output channel.** `classify_and_diff` currently returns `(to_apply: list[NormalizedDataset], DiffPayload)`. Extend to `(to_apply, to_version: list[VersionedDatasetPlan], DiffPayload)` where `VersionedDatasetPlan` carries everything the applier needs:

```python
@dataclass
class VersionedDatasetPlan:
    dataset_id: UUID
    current_version_num: int           # baseline (latest with bindings)
    next_version_num: int              # max_version_num + 1 (covers orphans)
    all_fields: list[NormalizedField]  # post-change field set, in source order
    unchanged_field_bindings: dict[str, FieldBindingSnapshot]
        # keyed by field name: {field_id, type_instance_id} reused as-is
    added_fields: list[NormalizedField]
    removed_field_ids: list[UUID]      # recorded in DiffPayload only; not applied
    type_changed_fields: list[NormalizedField]  # rebuild full tree
```

Note: `current_version_num` and `next_version_num` differ by more than 1 when an orphan exists (e.g. baseline v1, orphan v2, next = v3).

Existing bindings/trees fetched during diff are reused — no refetch in applier.

### Applier (`crawler/aide_crawler/applier.py`)

**New `apply_versioned_datasets(client, *, plans: list[VersionedDatasetPlan], type_cache: TypeCache) -> list[VersionedDataset]`**. For each plan:

1. `POST /dataset-schemas/` with `{dataset_id, version_num=plan.next_version_num}`. Unique constraint `(dataset_id, version_num)` returns 409 on race; applier re-raises (matches current no-isolation policy).

2. Compute fields needing a newly-created `TypeInstance` tree = `added_fields ∪ type_changed_fields`. For added fields, first `POST /fields/batch` to create `Field` rows (field rows are dataset-level, not version-scoped — one row per column for the lifetime of the dataset).

3. `POST /type-instances/batch` via the existing `_batch_create_type_trees` helper, which already flattens trees by depth and posts one batch per level. Returns `{field_id → root_type_instance_id}`.

4. Build the full binding set for the new version:
   - for each field in `plan.all_fields` (in source order), assign `position = index`
   - if name in `unchanged_field_bindings` → reuse `type_instance_id`
   - else (added or type-changed) → use freshly-created root
   - `is_nullable` from the normalized field
5. `POST /field-bindings/batch` with the full list.

Removed fields: no binding in the new version. Their `Field` rows stay (dataset-level).

**`apply_new_datasets` is left untouched** (including `_find_or_create_schema_v1`). It keeps its current "safe to rerun after partial failure" contract — which is how the edge case "differ finds an orphan-only dataset with no baseline" is handled: the runner routes such datasets through `apply_new_datasets` (existing-dataset branch via `existing_dataset_ids`), which picks up the orphan v1 and completes the missing bindings. This is a distinct recovery path from the versioned apply and is deliberately preserved.

### Runner (`crawler/aide_crawler/runner.py`)

- After `apply_new_datasets`, call `apply_versioned_datasets` with `to_version` from the diff step.
- Extend the `summary` JSON on `crawl_runs.update`:
  ```
  {
    new_datasets_applied: int,
    new_versions_created: int,          # NEW
    fields_added: int,                  # NEW (across versioned datasets)
    fields_removed: int,                # NEW
    type_changes_applied: int,          # NEW
    versioned_datasets: [               # NEW
      {dataset_id, object_name, old_version, new_version,
       added: int, removed: int, type_changes: int}
    ]
  }
  ```
- Status stays binary: `COMPLETED` on success, `FAILED` on any raise (inspection, auth, or apply). No `PARTIAL`.

### Reporter (`crawler/aide_crawler/reporter.py`)

Text output gains:

```
Crawl Summary
  New datasets:        18
  Versioned datasets:   3
  Fields added:        24
  Fields removed:       2
  Type changes:         5

Versioned Datasets:
  public.orders   v1 → v2   +1/-1/~1
  public.users    v3 → v4   +2/-0/~0
  public.items    v1 → v2   +0/-1/~2
```

JSON output: add `versioned_datasets[]` parallel to existing `new_datasets_applied[]`.

### SDK, schemas, backend

No changes.

## Data flow — worked example

System `pg-prod`, dataset `public.orders` at v1 with fields `id:INT`, `total:NUMERIC`, `created_at:TIMESTAMP`, `deleted_at:TIMESTAMP`. Source now has `id`, `total` unchanged; `status:VARCHAR` added; `created_at` → `TIMESTAMPTZ`; `deleted_at` removed.

```
Differ
  GET /dataset-schemas/?dataset_id=orders        → pick latest non-orphan = v1 (S1)
  GET /field-bindings/?dataset_schema_id=S1      → (id→TI-1), (total→TI-2),
                                                    (created_at→TI-3), (deleted_at→TI-4)
  GET /type-instances/{TI-*}/tree
  Diff:
    unchanged:      [id (TI-1), total (TI-2)]
    added:          [status]
    type_changed:   [created_at]
    removed:        [deleted_at]

Applier — versioned branch
  POST /dataset-schemas/          {dataset_id=orders, version_num=2} → S2
  POST /fields/batch              [status]                           → F-status
  POST /type-instances/batch      [new VARCHAR, new TIMESTAMPTZ]    → TI-5, TI-6
  POST /field-bindings/batch      [
    {S2, id,         TI-1, pos=0},   ← reuse
    {S2, total,      TI-2, pos=1},   ← reuse
    {S2, status,     TI-5, pos=2},   ← new field + new tree
    {S2, created_at, TI-6, pos=3},   ← existing field + new tree
    -- deleted_at: no binding
  ]

Runner
  PUT /crawl-runs/{id}  status=COMPLETED,
    summary={new_versions_created:1, fields_added:1, fields_removed:1,
             type_changes_applied:1, versioned_datasets:[...]},
    diff_payload={..., existing_datasets_diff:[
      {dataset_id:orders, current_version_num:1, new_version_num:2, ...}
    ]}
```

Post-state DB rows for `orders`: 2 `DatasetSchema` (v1, v2), 5 `Field` (original 4 plus `status`; `deleted_at` stays but unbound in v2), 6 `TypeInstance` (TI-1..4 shared with v1, TI-5/6 new), 4 `FieldBinding` in v1 + 4 in v2.

Next crawl with no source drift: differ picks v2, bindings match normalized result, diff empty, no new version created. Idempotent.

## Edge cases

- **Concurrent crawls on the same dataset.** Two runs each target `version_num=2`. The unique `(dataset_id, version_num)` constraint fails the second with 409. Applier re-raises → crawl run marked `FAILED`. Operator retries. Acceptable.
- **Orphan version from a prior partial run.** Prior run created `DatasetSchema` row but crashed before writing bindings. Next differ skips it (baseline filter: version must have at least one binding). On the new apply, `version_num` picker uses `max(version_num)` across *all* versions (including orphans) to avoid colliding on the orphan's number. Concretely: baseline scan uses "latest with bindings", next-version allocation uses `max(version_num) + 1` over all rows.
- **`VARCHAR(50)` → `VARCHAR(100)`** (same type code, different params). Differ's tree comparison treats parameters as part of the tree → counts as type change → rebuild full tree. Correct.
- **Nested type inner change** (e.g. `ARRAY<INT>` → `ARRAY<BIGINT>`). Tree comparison detects at leaf → full field tree is rebuilt (reuse only applies to whole-field tree identity, not subtree). Acceptable.
- **Add + remove net-zero (rename).** Treated as two independent operations. Old `Field` row stays unbound in new version; new `Field` row is created. No rename detection.
- **Unchanged dataset.** `to_version` list empty for that dataset → `apply_versioned_datasets` is a no-op for it. No spurious versions.
- **`is_nullable` flip without type change.** Differ currently does not detect it — no new version. Documented limitation.

## Testing

### Differ unit (`crawler/tests/test_differ.py`)

- `test_baseline_picks_latest_version` — seed schemas v1 and v2 (both with bindings), assert baseline = v2.
- `test_baseline_skips_orphan_version` — seed v1 (with bindings) + v2 (no bindings), assert baseline = v1.
- `test_diff_against_v2_detects_changes_from_v2` — seed v2 as baseline, mutate source, assert diff is computed against v2's bindings not v1's.

### Applier unit (`crawler/tests/test_applier.py`)

- `test_versioned_apply_increments_version_num` — baseline v1, no orphans → applier posts schema with `version_num=2`; baseline v5 → `version_num=6`.
- `test_versioned_apply_skips_orphan_version_number` — baseline v1, orphan v2 (no bindings) → applier posts `version_num=3`, not 2.
- `test_versioned_apply_reuses_unchanged_type_instance` — given `unchanged_field_bindings={"id": TI-1, "total": TI-2}`, assert the `FieldBinding` batch payload lists `TI-1` and `TI-2` verbatim; no new `TypeInstance` POST for those fields.
- `test_versioned_apply_creates_trees_for_added_fields` — assert `POST /fields/batch` is called with added fields and `POST /type-instances/batch` creates their trees.
- `test_versioned_apply_rebuilds_tree_for_type_changes` — assert new `TypeInstance` created; new binding points to it (not the old `TI-3`).
- `test_versioned_apply_omits_removed_fields` — assert binding batch has no entry for removed field.
- `test_versioned_apply_positions_match_source_order` — assert binding `position` matches index in source field list.
- `test_versioned_apply_409_on_version_collision_reraises` — mock `dataset_schemas.create` to raise 409; assert exception propagates.

### Runner (`crawler/tests/test_runner.py`)

- `test_runner_triggers_versioned_apply_when_diff_nonempty` — end-to-end with fake client: new dataset → v1; existing dataset with diff → v2; summary has `new_versions_created=1`.
- `test_runner_skips_versioned_apply_when_no_diff` — no drift → no `dataset_schemas.create` call; `new_versions_created=0`.

### Reporter (`crawler/tests/test_reporter.py`)

- `test_text_report_includes_versioned_datasets_section` — output contains `v{old} → v{new}` and `+/-/~` counts.
- `test_json_report_includes_versioned_datasets_array` — parsed JSON has `versioned_datasets` key.

### Integration

If a full end-to-end crawler test against a real metastore + source DB exists (check during implementation), add: seed dataset at v1, mutate source fixtures, re-crawl, assert v2 exists with expected bindings. Otherwise skip — unit coverage is enough for this scope.

### Backend tests

None. No backend changes.

## Changed files

- `crawler/aide_crawler/differ.py` — replace `_find_schema_v1_id` with `_find_baseline_schema` + `_find_max_version_num`, add orphan-skip filter for baseline, thread `current_version_num` through diff result, build `VersionedDatasetPlan` list.
- `crawler/aide_crawler/applier.py` — add `apply_versioned_datasets`; `apply_new_datasets` unchanged.
- `crawler/aide_crawler/runner.py` — call versioned apply after new-apply; route orphan-only datasets through `apply_new_datasets` recovery path; extend `summary`.
- `crawler/aide_crawler/reporter.py` — text + JSON versioned section.
- `crawler/tests/test_differ.py`, `test_applier.py`, `test_runner.py`, `test_reporter.py` — new cases per section above.

No changes to: `backend/`, `schemas/`, `sdk/`, `alembic/`, `docs/AIDE_data_model.json`.
