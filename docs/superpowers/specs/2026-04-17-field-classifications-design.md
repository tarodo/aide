# Field Classifications — extract `pii_tags` into dedicated append-only resource

## Problem

`pii_tags` lives on `fields.pii_tags` as an `ARRAY(Text)` column. PII classification has a different lifecycle from the structural schema:

- **Structural schema** (`dataset_schemas` + `field_bindings`) — crawler-driven, changes when DDL changes.
- **Classification** — manual (steward) in MVP, never automated by the crawler. Post-MVP crawler will detect PII but write it as a separate signal. Classification changes independently of DDL.

Keeping `pii_tags` on `Field` has two problems:

1. No audit history. Updating the column mutates in place.
2. If moved to `field_binding` (versioned with schema), every retag would bump `dataset_schema.version_num` and require carry-forward logic on every crawl. That couples two lifecycles that must stay independent.

Classification needs its own audit trail with immutable history.

## Solution

Extract classification into a new table `field_classifications`. Append-only: every change is a new row; the latest row by `created_at` is the current classification.

### Table

```
field_classifications
  id            UUID         PRIMARY KEY
  field_id      UUID         NOT NULL  REFERENCES fields(id) ON DELETE CASCADE
  pii_tags      TEXT[]       NOT NULL   -- [] = "no PII", [...] = tags; "not recorded" = no row exists
  reason        TEXT         nullable
  note          TEXT         nullable
  row_version   INT          NOT NULL DEFAULT 1
  created_at    TIMESTAMP    NOT NULL DEFAULT now()
  updated_at    TIMESTAMP    NOT NULL DEFAULT now()
  created_by    UUID         nullable
  updated_by    UUID         nullable

INDEX ix_field_classifications_field_id_created_at (field_id, created_at DESC)
INDEX ix_field_classifications_created_by (created_by)
INDEX ix_field_classifications_updated_by (updated_by)
```

Uses `MetaDataMixin` (the same one as `Field`, `FieldBinding`).

### Semantics

- **Append-only.** No `UPDATE`, no `DELETE` via API. Corrections = new row, optionally with `reason="correction"`.
- **Current classification** = latest row by `created_at` for a given `field_id`.
- **History** = all rows for a given `field_id`, ordered `created_at DESC`.
- **Absence of rows** = field has never been classified (distinct from `pii_tags=[]`, which means "classified as no PII").
- **Cascade on Field delete** — audit trail for a removed field is not preserved; consistent with the rest of the model.
- **Point-in-time query** = `WHERE field_id = X AND created_at <= t0 ORDER BY created_at DESC LIMIT 1`. Same index covers it.

### Why append-only (not SCD2)

- Immutable rows — nobody can rewrite history by updating `valid_to`.
- One write path (INSERT only), no transaction required for the close+insert pair.
- At AIDE scale (10k-100k fields, manual write volume) `DISTINCT ON (field_id)` is cheap. Covered by the `(field_id, created_at DESC)` index.
- "One current row" invariant is implicit (latest by `created_at`); no partial unique index needed.

## API

All under `/api/v1/field-classifications`.

```
POST   /field-classifications
  body: { field_id, pii_tags: list[str], reason?, note? }
  201 → FieldClassificationRead
  errors: FIELD_NOT_FOUND (404)

GET    /field-classifications/{id}
  200 → FieldClassificationRead
  404

GET    /field-classifications
  query: field_id?, dataset_id?, created_at__gte?, created_at__lte?, sort, page, size
  200 → Page[FieldClassificationRead]
  — history pattern: ?field_id=X&sort=-created_at

GET    /field-classifications/current/{field_id}
  200 → FieldClassificationRead   (latest row)
  404                              (field has no classification)

GET    /field-classifications/by-dataset/{dataset_id}/current
  200 → list[FieldClassificationRead]
  — one per field in the dataset that has ≥ 1 classification
```

`PUT`, `PATCH`, `DELETE` are not exposed. The CRUD router for this resource registers only `create`, `get_one`, `list`, plus the two custom endpoints above.

**`pii_tags` in the request body is required** (non-null). `[]` is valid and means "reviewed, no PII". Absence of a row represents "not yet classified".

**`dataset_id` filter** on list requires a JOIN through `fields`. Repository implements.

**Consumers that need "field + current classification":** make two calls — tree/list for fields, batch `/field-classifications/by-dataset/{dataset_id}/current` for classifications. No eager include in `FieldRead`/`FieldTree`.

## Backend changes

### Modify

- `backend/models/field.py` — drop `pii_tags` column.
- `schemas/aide_schemas/field.py` — drop `pii_tags` from `FieldBase`, `FieldUpdate`, `FieldTree`.
- `backend/schemas/field.py` — re-export picks up automatically.
- `tests/api/test_fields.py` — remove `pii_tags` assertions from existing tests.
- `docs/AIDE_data_model.json` — drop `f_fld_pii_tags`; add `field_classifications` table + FK relationship.

### New

- `backend/models/field_classification.py` — SQLAlchemy model.
- `backend/repositories/field_classification.py` — repo with:
  - `get_current(field_id)` — latest row or `None`.
  - `list_by_field(field_id)` — history, `created_at DESC`.
  - `list_current_by_dataset(dataset_id)` — batch current for a dataset's fields.
- `backend/services/field_classification.py` — service. Validates `field_id` exists. No `update`/`delete` semantics.
- `backend/api/v1/field_classifications.py` — router. Uses `create_crud_router` with `create`/`get_one`/`list` only; custom handlers for `/current/{field_id}` and `/field-classifications/by-dataset/{dataset_id}/current`.
- `schemas/aide_schemas/field_classification.py` — `FieldClassificationCreate`, `FieldClassificationRead`, `FieldClassificationFilter`.
- `schemas/aide_schemas/__init__.py` — export new schemas.
- `backend/schemas/field_classification.py` — re-export.
- `backend/schemas/filters.py` — add `FieldClassificationFilter` + `FIELD_CLASSIFICATION_SORTABLE`.
- `backend/core/errors.py` — add `FIELD_CLASSIFICATION_NOT_FOUND`.
- `backend/db/uow.py` — register `field_classifications` repo.
- `backend/main.py` — register router.
- `backend/models/__init__.py`, `backend/services/__init__.py`, `backend/schemas/__init__.py` — wire imports.

### Alembic

One migration. Clean DB — no data migration.

```python
op.drop_column("fields", "pii_tags")
op.create_table(
    "field_classifications",
    sa.Column("id", sa.UUID(), primary_key=True),
    sa.Column("field_id", sa.UUID(), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
    sa.Column("pii_tags", postgresql.ARRAY(sa.Text()), nullable=False),
    sa.Column("reason", sa.Text(), nullable=True),
    sa.Column("note", sa.Text(), nullable=True),
    sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    sa.Column("created_by", sa.UUID(), nullable=True),
    sa.Column("updated_by", sa.UUID(), nullable=True),
)
op.create_index(
    "ix_field_classifications_field_id_created_at",
    "field_classifications",
    ["field_id", sa.text("created_at DESC")],
)
op.create_index("ix_field_classifications_created_by", "field_classifications", ["created_by"])
op.create_index("ix_field_classifications_updated_by", "field_classifications", ["updated_by"])
```

Downgrade: drop table, re-add `fields.pii_tags TEXT[]`.

## SDK changes

- `sdk/aide_sdk/resources/field_classifications.py` — new resource with `create`, `get`, `list`, plus `get_current(field_id)`, `list_history(field_id)`, `list_current_by_dataset(dataset_id)`.
- `sdk/aide_sdk/client.py` — register `FieldClassificationsResource`.
- `sdk/tests/` — add resource tests; remove any `field.pii_tags` references from existing tests.

**Breaking change:** `FieldRead.pii_tags` is gone. Consumers using `field.pii_tags` must migrate to the new resource.

## Crawler

No code changes. The crawler has never written `pii_tags` — it defaults to `None` in `FieldCreate`.

Post-MVP PII detector is out of scope for this spec. It will write to `/field-classifications` directly with an appropriate `reason` and `note`, without bumping `dataset_schema.version_num`.

## Testing

### Backend

**`tests/models/test_field_classification.py`**
- Cascade delete: deleting a `Field` removes all its classifications.

**`tests/repositories/test_field_classification_repository.py`**
- `get_current(field_id)` returns the most recent row.
- `get_current(field_id)` returns `None` when no rows exist.
- `list_by_field(field_id)` returns history sorted `created_at DESC`.
- `list_current_by_dataset(dataset_id)` returns one current row per classified field, only fields belonging to the given dataset.
- Append-only: two sequential creates for the same `field_id` create two rows; `get_current` returns the latest.

**`tests/services/test_field_classification_service.py`** (mocked UoW)
- POST with non-existent `field_id` raises `FIELD_NOT_FOUND`.
- Successful create returns the Read DTO.
- `update`/`delete` not implemented — router does not register them.

**`tests/api/test_field_classifications.py`**
- POST happy path → 201 + Read DTO.
- POST with non-existent `field_id` → 404.
- POST with `pii_tags=[]` → 201 (valid "no PII").
- POST missing `pii_tags` → 422.
- GET `/{id}` → 200 / 404.
- GET list with `field_id=X&sort=-created_at` → history in expected order.
- GET list with `dataset_id=X` → only classifications from that dataset's fields.
- GET `/current/{field_id}` → latest row / 404 when unclassified.
- GET `/field-classifications/by-dataset/{dataset_id}/current` → batch, one per classified field.
- PUT / PATCH / DELETE → 405.

**`tests/api/test_fields.py`**
- Remove `pii_tags` from existing field CRUD tests.
- Verify `FieldRead` response does not include `pii_tags`.
- POST `/fields` with `pii_tags` in body — confirm behavior matches Pydantic config (422 if `extra='forbid'`, ignored otherwise). Pin whichever is current.

### SDK

- `FieldClassificationsResource` create/get/list basic cases.
- Special methods: `get_current`, `list_history`, `list_current_by_dataset`.
- Clean up existing SDK tests that reference `field.pii_tags`.

### Crawler

- Run existing crawler suite as a sanity check. No expected changes.

## Downstream doc updates (out of scope, separate PR)

- `docs/superpowers/specs/2026-04-15-frontend-mantine-spa-design.md` — mentions `PiiTagsInput` inside `FieldForm`. After this change, classification becomes its own resource; frontend needs a dedicated classification component.
- `docs/superpowers/plans/2026-04-15-frontend-roadmap.md` — same.
- `README.md` line 18 ("PII Tagging — Tag fields with PII markers") remains accurate.

## Non-goals

- Steward UX endpoint (`POST /datasets/{id}/retag` or similar). Current scope: raw CRUD. Revisit after MVP.
- Eager inclusion of classifications inside `FieldRead` / `FieldTree`.
- Auto-detection of PII in the crawler.
- Tag vocabulary/standardization. `pii_tags` stays `TEXT[]` with free-form strings.

## Risks

- **SDK consumers using `field.pii_tags`** break. Current scope: only `tests/api/test_fields.py` — trivial to update. No external consumers exist yet.
- **Double-write consistency** on corrections. Mitigation: stewards are trained that corrections = new POST with `reason="correction"`.
