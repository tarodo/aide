# ADR-011: YAML-Driven Reference Data Seeding

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

Some AIDE entities are **reference data** — they describe the world
AIDE knows about, not the user's catalogue:

- `SystemKind` — top-level taxonomy (`rdbms`, `kafka`, `storage`, …).
- `SystemFlavor` — a specific vendor + version family under a kind
  (`postgres14` under `rdbms`).
- `DataType` — each type a flavor supports, with a `params_schema`
  (e.g. `decimal(precision, scale)` with constrained ranges) and a
  `render_template` used to project the type back to a DDL string.

These rows are not created by end users through the API. They are
authored by the AIDE team: adding a new flavor (`postgres16`), adding
a new type (`bpchar`), adjusting a `render_template`, or extending a
`params_schema`. They must exist before any user can register a
concrete `TypeInstance` that references a type.

We need a mechanism for **authoring and applying** this data that:

1. Keeps the canonical definition in version control alongside the
   code that consumes it.
2. Is **idempotent** — running it twice against the same database is a
   no-op; running it after a code change applies only the diff.
3. Is **soft-delete-aware** (ADR-006) — re-running after a soft-delete
   should restore the row, not duplicate it or stay deleted.
4. Is **data-safe** — removing an entry from the source of truth must
   not silently hard-delete rows that `TypeInstance` foreign keys
   already point at.
5. Lives outside the Alembic migration chain — reference-data edits
   are frequent and should not accumulate 50 one-liner migrations.

## 2. Options Considered

### Option A: YAML per flavor + idempotent upsert script — **chosen**

- One YAML file per flavor under `backend/scripts/data/`
  (e.g. `postgres14.yaml`). Each file declares its `kind`, `flavor`,
  and the full list of `types`.
- A script (`backend/scripts/seed_data_types.py`) loads the YAML into
  a Pydantic `SeedFile`, upserts the kind, flavor, and types via
  `seed_from_file`, and prints a diff-shaped report.
- Upsert semantics per row: `inserted` / `updated` / `unchanged` /
  `restored` (un-soft-deleted).
- Types removed from the YAML are **not** removed from the database —
  they persist to protect `TypeInstance` FKs.
- The script ships with `--dry-run` (rollback on exit) and runs
  inside the backend container's `uv` environment.

| Dimension | Assessment |
|-----------|------------|
| Authoring ergonomics | **High** — YAML + a dict-per-type is dense and readable |
| Idempotency | **High** — every re-run is a diff |
| Safety | **High** — no silent hard-delete; soft-deleted rows are auto-restored |
| Git-reviewability | **High** — a diff of the YAML reads like a changelog |
| Coupling to migrations | **None** — seed runs are independent of Alembic |

**Pros:**

- Reviewers read the intent of a change in one file (`+1 type`,
  `render_template changed`), not by reverse-engineering a SQL
  migration.
- The Pydantic envelope (`SeedFile`, `SeedKind`, `SeedFlavor`,
  `SeedType`, `SeedParamSpec`) validates the YAML with
  `model_config = ConfigDict(extra="forbid")` — a typo in a field
  name fails loudly at load time, not silently at use time.
- A `_unique_codes` validator rejects duplicate type codes within a
  file; an otherwise-silent duplicate would corrupt the upsert.
- Restoring a soft-deleted reference row is automatic: the upsert
  detects `deleted_at IS NOT NULL` and clears it. Operators do not
  have to know this; re-running the seeder "fixes" the data.
- YAML is cheap to diff, cheap to generate (the
  [postgres14.yaml](../../backend/scripts/data/postgres14.yaml) is
  hand-written, but can be machine-produced for other vendors).

**Cons:**

- The YAML schema is a second source of truth that must mirror the
  ORM columns it targets. A migration that adds a new column to
  `DataType` must be paired with a matching field on `SeedType` and
  a YAML update.
- Soft-deleting a type manually via the API will be silently undone
  on the next seeder run — **intentional** but surprising.
- Removed-from-YAML types remain in the DB; they must be pruned by
  hand when genuinely unwanted. (See §5 "Pruning" below.)

### Option B: Alembic data migration per change

Every reference-data edit ships as a dedicated Alembic migration
(`op.bulk_insert`, `op.execute(text("UPDATE ..."))`).

**Pros:** uses existing migration chain; natural rollback via
downgrade.
**Cons:** a flavor with 40 types grows into dozens of migrations
(40 inserts, then updates, then reorders) that have nothing to do
with schema; downgrade scripts for reference-data churn are
error-prone; running one migration out of order has no defined
semantics.

### Option C: Hard-coded Python fixtures

A module (`backend/fixtures/postgres14.py`) listing Python objects
that are inserted on demand.

**Pros:** type-checked by mypy; easy to IDE-navigate.
**Cons:** poor diffability (a PR moves 15 objects around for a single
`name` change); mixing data and code discourages non-engineer
contributions; easy for structure-only validation (existence of
fields) to miss value-level issues that Pydantic would catch.

### Option D: Administrative API endpoints

Expose `POST /admin/system-kinds`, `POST /admin/data-types`, etc.,
and bootstrap the DB via an operator script that hits the endpoints.

**Pros:** reuses the write path that application code already tests.
**Cons:** the catalogue's own endpoints are user-facing and subject
to auth, audit, and rate limits we do not want in reference-data
flows; the "administrative bootstrap" is a separate concern and
acquires its own complexity.

### Option E: Database-only (managed outside source control)

Treat reference data as operational state that a DBA maintains.

**Pros:** no source control of the values.
**Cons:** the values determine application behaviour (allowed types,
render templates); drift between production and test environments
becomes undebuggable; onboarding a new environment requires a
human.

## 3. Trade-off Analysis

The tension is **version-controlled authoring vs. migration machinery
load**. Option B keeps everything in one tool (Alembic) but hijacks
the tool's purpose. Options C and E lose either readability or
reproducibility. Option D reuses the wrong path — administrative
bootstrap and user-driven writes have different authorization models.
Option A keeps reference data diff-friendly, safe to re-run, and
decoupled from schema migrations.

## 4. Recommendation

Adopt Option A. YAML is the source of truth; the seeder owns the
upsert semantics; Alembic only owns schema.

## 5. Implementation Notes

### File layout and naming

```
backend/scripts/data/
├── __init__.py
└── <flavor-code>.yaml        # one file per SystemFlavor
```

`flavor.code` is the filename stem (e.g. `postgres14.yaml` for a
flavor with `code: postgres14`). This makes "which file defines this
flavor?" trivial to answer and is the convention every new flavor
follows.

### YAML structure

```yaml
kind:
  code: rdbms
  name: Relational Database
flavor:
  code: postgres14
  name: PostgreSQL
  vendor: PostgreSQL Global Development Group
  versions: ["14"]
types:
  - code: integer
    params_schema: {}
    render_template: integer
  - code: decimal
    params_schema:
      precision: {type: int, required: false, default: null, min: 1, max: 1000}
      scale:     {type: int, required: false, default: null, min: -1000, max: 1000}
    render_template: "decimal({precision},{scale})"
```

- `kind` and `flavor` are singletons per file. A YAML file always
  defines one flavor under one kind.
- `types` is a flat list; duplicate `code` entries are rejected by
  the `SeedFile._unique_codes` validator.
- Each `type` carries an optional `params_schema` mapping param name →
  `{ type: int|str|bool, required, default, min, max }` — keep the
  shape aligned with the `SeedParamSpec` model in
  [`_seed_core.py`](../../backend/scripts/_seed_core.py:18).
- `render_template` is the DDL rendering for the type; placeholders
  are bracketed param names (`"decimal({precision},{scale})"`).

### Running the seeder

```
uv run python -m backend.scripts.seed_data_types \
    --file backend/scripts/data/postgres14.yaml
```

- Runs inside the backend `uv` environment so it picks up the same
  SQLAlchemy models the app uses.
- The script opens one `AsyncSessionLocal()` transaction, upserts the
  full file, and `commit`s on clean exit. `--dry-run` rolls back
  instead and is useful for PR review.
- The printed report lists `types: +<inserted> ~<updated>
  =<unchanged> restored=<restored>`, which maps directly to the
  per-row statuses returned by the upsert helpers.

### Upsert semantics

Per row, the seeder returns one of four statuses:

| Status | Condition | Action |
|--------|-----------|--------|
| `inserted` | No row with this code exists | `INSERT` |
| `restored` | Row exists but `deleted_at IS NOT NULL` | Clear `deleted_at`, apply all fields |
| `updated` | Row exists (active), at least one field differs | Apply changed fields |
| `unchanged` | Row exists (active), all fields equal | No-op |

This is enforced by dedicated helpers:
[`upsert_system_kind`](../../backend/scripts/_seed_core.py:90),
[`upsert_system_flavor`](../../backend/scripts/_seed_core.py:116),
[`upsert_data_type`](../../backend/scripts/_seed_core.py:165). Each
compares the subset of fields the YAML owns — extra columns that the
YAML does not describe (audit columns, `row_version`) are untouched.

### What the seeder does **not** do

- It does not delete rows that are absent from the YAML. A
  `SystemFlavor` (or `DataType`) that used to exist and is now absent
  from the authoritative file remains in the database so that
  `TypeInstance` FKs (and any other downstream references) continue
  to resolve. **This is intentional.** Deleting a type would cascade
  against valuable user data; the trade-off is that a stale row may
  linger.
- It does not run schema changes. Any column added to `SystemKind`,
  `SystemFlavor`, or `DataType` requires an Alembic migration first;
  the seeder only fills values for columns that already exist.
- It does not manage users, credentials, or any transactional data.

### Pruning a removed entry

When a reference row must actually go away (e.g. a `DataType` that is
*known* not to be referenced anywhere):

1. Confirm no `TypeInstance` rows (or other FKs) point at the row.
   If they do, migrate them to the replacement first.
2. Soft-delete through the API or a targeted one-off SQL statement.
3. Remove the entry from the YAML file.
4. Do not run the seeder against a new production DB until step 1 is
   complete — otherwise the seeder will `restore` the row.

### Adding a new flavor

1. Copy an existing YAML as a template (e.g. `postgres14.yaml` →
   `mysql8.yaml`).
2. Edit `kind`, `flavor`, and `types` for the new flavor. Ensure
   every type's `params_schema` param uses only `int | str | bool`
   (the current `SeedParamSpec.type` alphabet). Extending the
   alphabet requires updating the Pydantic model.
3. Run the seeder with `--dry-run` first; inspect the report.
4. Run without `--dry-run`.
5. Commit the YAML; no migration required.

### Adding a new type to an existing flavor

1. Add the `type` entry to the flavor's YAML.
2. Run the seeder; confirm `+1` inserted.
3. Commit the YAML.

### Integration with tests

Tests do not need reference data unless they touch `TypeInstance` or
`CastRule` rows. Repository and service tests use fixtures to create
the specific reference rows they need (see ADR-007). The YAML seeder
is out of the per-test path.

### Why we rejected auto-seeding at startup

The FastAPI `lifespan` hook only runs `ensure_initial_superuser`
([`main.py:41`](../../backend/main.py:41)). Auto-running the seeder
at startup would:

- Tie application boot to external state changes (boot would fail
  because a YAML got malformed).
- Hide the diff from operators (a reference-data change lands
  silently on deploy).
- Compete with per-request transactions for the same tables.

Seeding is an explicit, operator-invoked step. Automating its
invocation belongs in the deployment pipeline, not in the app.

## 6. Consequences

- **Easier:** adding or amending reference data is a single-file PR
  with a `--dry-run` preview; soft-deleted rows self-heal on the next
  run; the `TypeInstance` FK surface is protected by default.
- **Harder:** hard-delete of a reference row is a manual, multi-step
  operation; the YAML schema must track ORM column changes; nothing
  stops an operator from editing `data_types` directly in SQL and
  diverging from the YAML.
- **Revisit when:** the number of flavors grows past single digits
  and per-file hand editing becomes tedious (consider code-gen from
  a registry) or when reference-data churn justifies its own
  migration-like tool (e.g. with a real delete path gated on FK
  checks).
