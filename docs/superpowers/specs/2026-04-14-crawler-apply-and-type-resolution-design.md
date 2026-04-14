# Crawler: Apply Mode + Metastore-Driven Type Resolution

Date: 2026-04-14
Status: Design approved

## Problem

Crawler currently computes a diff between a source RDBMS and the metastore, but never writes anything back. An empty metastore stays empty after a crawl.

Crawler also ships its own `type_map.py` mapping SQLAlchemy types to string codes. The map is incomplete and drifts from the canonical DataType catalogue seeded by `backend/scripts/seed_data_types.py` from per-flavor YAML files.

## Goals

1. Crawler populates new tables automatically on first encounter.
2. Existing tables never mutate implicitly — all changes land in a structured diff attached to the `CrawlRun`.
3. The metastore owns type validation. Crawler resolves `code → data_type_id` via metastore catalogue; unknown types fail fast.

## Non-goals

- Auto-removal of datasets/fields dropped at the source (diff-only).
- Nested/struct fields (`Field.parent_id` stays untouched).
- Cross-flavor migration or type casting.
- UI/CLI flags for apply/diff modes (single auto-mode).

## Architecture

```
crawler run
  ├── fetch System + flavor_id from metastore
  ├── GET /data_types?system_flavor_id={flavor_id}
  │     → build cache: {code → data_type_id}
  ├── run_inspection (SQLAlchemy Inspector)
  ├── normalize: each column → (code, params) via crawler type_map
  │     unknown SA type OR code missing in cache → raise, crawl_run.status=failed
  ├── classify datasets by object_name:
  │     absent in metastore → apply (create Dataset + Fields + TypeInstances)
  │     present in metastore → diff only
  ├── compute_diff for existing datasets (new/removed fields, type changes)
  └── crawl_runs.update(status=completed, summary=counts, diff_payload=full_diff)
```

Boundary:
- **Crawler** — SA→code mapping (dialect-specific), orchestration, apply of new datasets, diff computation.
- **Metastore** — stores DataType catalogue, validates `TypeInstance.type_params` against `DataType.params_schema`, exposes flavor-scoped DataType listing.

## Components

### Backend

- `backend/models/crawl_run.py` — add `diff_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)`.
- Alembic migration adding the column (nullable, default NULL).
- `backend/schemas/crawl_run.py` — add `diff_payload: dict | None` to `CrawlRunUpdate` and response schema.
- `backend/services/type_instance.py` — on create/update, validate `type_params` against the related `DataType.params_schema`:
  - Required keys present
  - Type coercion (`int`, `str`, etc.)
  - `min` / `max` bounds for numeric params
  - Reject unknown param keys
  - Raise 422 with a descriptive error on failure.
- `backend/api/v1/data_types.py` — no change; `GET /data_types?system_flavor_id=X` already used by crawler.

### Crawler

- `crawler/aide_crawler/type_map.py`
  - Extend `GENERIC_TYPE_MAP` and `DIALECT_TYPE_MAP` to cover every code present in `backend/scripts/data/postgres14.yaml`.
  - Replace `Optional[TypeMapping]` return with exceptions: `UnknownTypeError` when no mapping matches. No silent `None`/warning path.
- `crawler/aide_crawler/type_cache.py` (new)
  - Loads `GET /data_types?system_flavor_id=X` once per run.
  - Exposes `resolve(code: str) → UUID`; raises `TypeNotInFlavorError` if code missing.
- `crawler/aide_crawler/applier.py` (new)
  - `apply_new_datasets(client, datasets, type_cache, dialect_name) → list[AppliedDataset]`.
  - Idempotent: re-checks dataset existence by `(system_id, object_name)` before create; re-checks field existence by `(dataset_id, name, parent_id is null)` before create.
  - Full write chain per new dataset: `Dataset` (kind=`rdbms`) → `DatasetSchema` (version_num=1) → per column `{Field, TypeInstance, FieldBinding(position, is_nullable)}`.
  - `NormalizedField` gains `nullable: bool` and `position: int` (currently absent) so binding data is available downstream.
- `crawler/aide_crawler/differ.py`
  - Refactor to return classified structure: `(to_apply: list[NormalizedDataset], to_diff: DiffPayload)`.
  - Existing-dataset path computes: `new_fields`, `removed_fields`, `type_changes` (compare by `(code, normalized_params)`).
- `crawler/aide_crawler/runner.py`
  - New orchestration: load cache → normalize → classify → apply → diff existing → update crawl_run with `summary` + `diff_payload`.
- `crawler/aide_crawler/reporter.py` — update to render new diff structure including applied datasets.

### SDK

- `DatasetsResource`, `FieldsResource`, `TypeInstancesResource`, `DatasetSchemasResource` already exist. No new resources. Crawler consumes all four.

## Data model: `diff_payload`

```json
{
  "schema_version": 1,
  "new_datasets_applied": [
    {"object_name": "public.users", "dataset_id": "uuid", "fields_count": 12}
  ],
  "existing_datasets_diff": [
    {
      "object_name": "public.orders",
      "dataset_id": "uuid",
      "new_fields": [
        {"name": "shipped_at", "code": "timestamp", "params": {}}
      ],
      "removed_fields": [
        {"name": "legacy_col", "field_id": "uuid"}
      ],
      "type_changes": [
        {
          "field_name": "amount",
          "field_id": "uuid",
          "old": {"code": "numeric", "params": {"precision": 10, "scale": 2}},
          "new": {"code": "numeric", "params": {"precision": 14, "scale": 4}}
        }
      ]
    }
  ],
  "removed_datasets": [
    {"object_name": "public.old_table", "dataset_id": "uuid"}
  ]
}
```

- `new_datasets_applied` records what the crawler wrote (audit, not pending).
- `removed_*` is diff-only; metastore rows are never deleted by crawler.
- `type_changes` uses a normalized params comparator so `{precision: 10}` vs `{"precision": 10}` do not produce false positives.

## Error handling

Failure modes, all terminate the run with `crawl_run.status=failed` and a descriptive `error_message`:

| Condition | Exception |
|-----------|-----------|
| SA type has no entry in type_map | `UnknownTypeError(dialect, sa_class_name)` |
| Code not present in flavor DataType cache | `TypeNotInFlavorError(code, flavor_code)` |
| Metastore rejects TypeInstance params | propagate 422 body into `error_message` |
| Flavor has zero DataTypes | existing check in `runner.py` retained |
| Network / auth | existing behavior |

Apply stage is not transactional across datasets. Idempotency (existence check before create) protects reruns after a partial failure. A single dataset may end up partially populated (Dataset created, DatasetSchema or some FieldBindings missing) if the process is killed mid-apply; the next run detects partial state by listing existing Fields for the dataset and completing the missing FieldBinding/TypeInstance rows.

## Edge cases

- **Renamed table** → appears as `removed_datasets` + `new_datasets_applied`. Manual reconciliation.
- **Renamed column** → `removed_fields` + `new_fields` within the same dataset diff.
- **Views** → same code path as tables (`is_view=True`).
- **Empty metastore** → every discovered dataset lands in `new_datasets_applied`, `existing_datasets_diff` is empty.
- **Rerun with no changes** → `diff_payload = {schema_version: 1, new_datasets_applied: [], existing_datasets_diff: [], removed_datasets: []}`.

## Testing

**Backend**
- `tests/services/test_type_instance.py` — params_schema validation: required missing, min/max bounds, type coercion, unknown param key, happy path for `numeric(10,2)`.
- `tests/models/test_crawl_run.py` — `diff_payload` JSONB round-trip.
- Alembic migration up/down verified locally.

**Crawler** (standalone `cd crawler && uv run pytest tests/`)
- `tests/test_type_map.py` — every code in `postgres14.yaml` maps, dialect types (`JSONB`, `INET`, `UUID`) resolve correctly, unknown type raises `UnknownTypeError`.
- `tests/test_type_cache.py` — cache built from paginated list response, missing code raises `TypeNotInFlavorError`.
- `tests/test_applier.py` — mocked SDK: create dataset on empty state; rerun skips existing dataset and only fills missing fields; TypeInstance receives `{data_type_id, type_params}`.
- `tests/test_differ.py` — three scenarios: all-new, mixed new/existing, all-existing with mutations.
- `tests/test_runner_integration.py` — end-to-end with mocked SDK; asserts crawl_run.update called with expected `diff_payload` and `summary`.
- Golden test: a fixture PG14 with three tables, snapshot `diff_payload` JSON.

**Manual smoke**
- Empty metastore run → every table in `new_datasets_applied`, nothing in diff.
- Second run unchanged → empty diff.
- Add a column at source, rerun → appears in `existing_datasets_diff[].new_fields`.
- Drop a column at source → appears in `removed_fields`.
- Change `numeric(10,2)` → `numeric(14,4)` → appears in `type_changes`.

## Migration / rollout

1. Ship backend migration + `type_params` validation first; existing crawls continue to work (no `diff_payload` writes).
2. Ship crawler changes; `diff_payload` starts being populated.
3. Backfill is not required — historical `CrawlRun` rows keep `diff_payload=NULL`.

## Open questions

None at design time. Implementation plan may surface more.
