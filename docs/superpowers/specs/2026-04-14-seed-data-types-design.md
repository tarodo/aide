# Seed Data Types — Design

**Date:** 2026-04-14
**Scope:** Pre-load `DataType` rows (and supporting `SystemKind` / `SystemFlavor`) for PostgreSQL 14 so the crawler's FK lookups resolve. Reusable runner for future flavors (PG15, MySQL8, etc.).

## Goal

Provide a standalone, idempotent script that populates the metastore with the full set of built-in PostgreSQL 14 data types, driven by a curated YAML file. The YAML is the source of truth; Context7 is used **once** offline to help generate it, not at runtime.

## File Layout

```
backend/scripts/
  seed_data_types.py            # runner, flavor-agnostic
  data/
    postgres14.yaml             # curated types (generated via Context7, then reviewed)
tests/scripts/
  test_seed_data_types.py       # pytest for runner
```

## YAML Schema

```yaml
kind:
  code: rdbms
  name: Relational Database
flavor:
  code: postgres14
  name: PostgreSQL 14
  vendor: PostgreSQL Global Development Group
  versions: ["14"]
types:
  - code: varchar
    params_schema:
      length: {type: int, required: false, default: null}
    render_template: "varchar({length})"
  - code: numeric
    params_schema:
      precision: {type: int, required: false, default: null}
      scale:     {type: int, required: false, default: null}
    render_template: "numeric({precision},{scale})"
  - code: bigint
    params_schema: {}
    render_template: "bigint"
  # ~50 entries total, covering all built-in PG14 types
```

**`params_schema` shape** (simple param spec):
- Object keyed by param name.
- Each value: `{type: int|str|bool, required: bool, default: <any>}`.
- Empty object `{}` means "no params".

**`render_template`**: Python `str.format`-style template used to render a `TypeInstance` back to PG native SQL (e.g. `varchar({length})` → `varchar(255)`). Nullable for types with non-trivial rendering (handled later by code).

## Type Coverage (PG14, everything built-in)

Curated list to include (~50 entries). Groups:

- **Numeric:** smallint, integer, bigint, decimal, numeric, real, double, smallserial, serial, bigserial, money.
- **Character:** char, varchar, text.
- **Binary:** bytea.
- **Date/Time:** date, time, timetz, timestamp, timestamptz, interval.
- **Boolean:** boolean.
- **Enumerated:** enum (meta; instance carries label list).
- **Geometric:** point, line, lseg, box, path, polygon, circle.
- **Network:** inet, cidr, macaddr, macaddr8.
- **Bit strings:** bit, varbit.
- **Text search:** tsvector, tsquery.
- **UUID:** uuid.
- **XML / JSON:** xml, json, jsonb.
- **Arrays:** array (meta; child `TypeInstance` carries element).
- **Ranges:** int4range, int8range, numrange, tsrange, tstzrange, daterange.
- **Object identifier:** oid, regclass, regproc, regtype, regnamespace, regrole, regconfig, regdictionary.
- **Pseudo / system:** pg_lsn, txid_snapshot.

Generation step: query Context7 `/postgresql/postgresql` docs (chapter 8 "Data Types") → draft YAML → manual review before commit.

## Script Flow (`seed_data_types.py`)

1. **Args:** `--file <path>` (required), `--dry-run` (optional).
2. **Load + validate:** parse YAML, validate via small Pydantic model (`SeedFile` with `kind`, `flavor`, `types`). Fail fast on malformed input.
3. **Session:** open `AsyncSession` via existing `backend.db.session`.
4. **Upsert `SystemKind`** by `code`:
   - If row exists and active → reuse id.
   - If row exists but soft-deleted → restore (clear `deleted_at`), update `name`.
   - Else insert.
5. **Upsert `SystemFlavor`** by `code` (FK to kind id from step 4).
6. **Upsert `DataType`** per type, key `(system_flavor_id, code)`:
   - Insert if absent.
   - Update `params_schema` / `render_template` if changed.
   - Restore + update if soft-deleted.
7. **Commit** (or rollback for `--dry-run`).
8. **Report:** log `kind: created|existing`, `flavor: …`, `types: N inserted, M updated, K unchanged`.

## Idempotency Policy

- Primary natural key: `(system_flavor_id, code)` for `DataType`; `code` for kind + flavor.
- Re-running with same YAML → no writes (all "unchanged").
- Editing a type in YAML → UPDATE.
- Adding a type → INSERT.
- **Removing a type from YAML → left alone.** No auto-delete. Operators prune manually if needed; protects existing `TypeInstance` rows.

## Error Handling

- Any validation or DB error → full rollback, non-zero exit.
- No partial seed: the whole file is applied in one transaction.

## Invocation

```bash
uv run python -m backend.scripts.seed_data_types \
  --file backend/scripts/data/postgres14.yaml
```

Dry run:
```bash
uv run python -m backend.scripts.seed_data_types \
  --file backend/scripts/data/postgres14.yaml --dry-run
```

## Testing

`tests/scripts/test_seed_data_types.py` (runs in Docker via `make test-docker`):

- **Happy path:** seed empty DB, assert kind/flavor/types rows match YAML.
- **Idempotency:** run twice, second run reports 0 inserts, 0 updates.
- **Update:** change `render_template` in YAML, re-run, assert UPDATE happens.
- **Soft-delete restore:** mark flavor `deleted_at`, re-run, assert restored.
- **Malformed YAML:** missing `flavor.code` → Pydantic validation error, no rows written.
- **Dry run:** rolls back, DB unchanged.

## Out of Scope

- No MySQL / PG15 YAML in this spec (future work, same runner).
- No automatic pruning of types removed from YAML.
- No runtime Context7 calls.
- No admin UI for editing types (direct YAML edit + re-run).

## Open Risks

- `params_schema` shape is custom (not JSON Schema). If future validator needs stricter spec, migration required. Acceptable trade-off for readability now.
- `render_template` format (`str.format`) assumes param names are valid Python identifiers. PG14 type params satisfy this.
