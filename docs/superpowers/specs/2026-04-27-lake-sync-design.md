# Lake-Sync — Source-to-Lake Target Provisioning

**Date:** 2026-04-27
**Status:** Draft (awaiting review)
**Scope:** A single backend operation that creates a lake target dataset (Iceberg-on-HMS) from an already-crawled source dataset. Mirrors source fields, picks lake types via shared `CastRule`, optionally applies a `TechFieldTemplate`, and pins a `DatasetLink` between source and target. DDL emission is deferred — see Non-Goals.

**Related ADRs:** ADR-008 (polymorphic Dataset), ADR-016 (two-level lineage), ADR-017 (tech-field templates), ADR-018 (schema-pinned lineage), ADR-010 (enum-as-varchar). New: ADR-019 (lake-sync — single `CastRule` table, `iceberg_v2` flavor, deferred DDL).

---

## 1. Context and Problem

The crawler discovers source tables (Postgres 14 today) and writes the `Dataset` → `DatasetSchema` → `Field` → `FieldBinding` → `TypeInstance` chain. Phase 3 schema-pinned lineage shipped: a `DatasetLink` can pin source/target schemas and a compatibility report grades each field-pair via `CastRule.safety`.

What is still manual: when a new source table appears, an engineer must create the matching lake target by hand — pick a target name, decide each column's lake type, write target `Field`/`FieldBinding`/`TypeInstance` rows, then create the `DatasetLink`. This is repetitive, error-prone, and disconnected from the type catalog the metastore already knows.

The goal of this phase is one backend call: "given source dataset X and target lake system Y, produce the full target chain plus a pinned `DatasetLink`, picking lake types from default rules and accepting per-field overrides."

The lake stack is fixed for this phase: Apache Iceberg v2 (Parquet under the hood) on Hive Metastore. Engines (Impala, Spark) read these tables but are irrelevant to the metastore — engine-specific concerns (DDL dialect, runtime config) belong in a later phase.

## 2. Goals / Non-Goals

**Goals:**

- New endpoint `POST /api/v1/datasets/{source_dataset_id}/lake-sync` that creates the full target chain in one atomic transaction.
- Reuse the existing `CastRule` table for both schema-evolution compatibility (Phase 3) and source-to-lake type translation (this phase). One table, two query lenses.
- New `SystemKind=hive` + `SystemFlavor=iceberg_v2` registered via the existing seed pipeline. New `iceberg_v2.yaml` data-type seed grounded in the Apache Iceberg v2 spec.
- New `casts_pg14_to_iceberg_v2.yaml` seed for default `CastRule` rows, plus a new `seed_cast_rules.py` script.
- Optional `tech_template_id` in the request: lake-sync also creates `Field(origin="tech")` + `FieldBinding` rows for the template's fields in the same transaction. Reuses existing `tech_type_resolver.yaml`, which we extend with an `iceberg_v2` branch.
- `DatasetLink` pinned to source's latest non-orphan `DatasetSchema` and the freshly created target `DatasetSchema v1`. `FieldLink` rows for every mapped target field (1:1 to source).
- Lockstep bump of `aide-schemas` and `aide-sdk`. `aide-crawler` does not change in this phase.

**Non-Goals (deferred):**

- **DDL rendering.** Engine and layer determine DDL dialect — too many dimensions for one phase. Phase will be opened separately once stakeholders decide engine-by-layer mapping.
- **Batch lake-sync over a whole crawl run.** Per-call scope is one source → one target. Engineer reviews each.
- **Schema evolution on the lake side** (re-run lake-sync to bump target `DatasetSchema`). Initial creation only; subsequent edits go through existing `DatasetSchema`/`FieldBinding` APIs.
- **Executing the result** against a live HMS / Iceberg catalog. Pure metastore operation.
- **`SystemKind=hive` instances beyond Iceberg v2.** Future Iceberg v3 (variant, geometry, timestamp_ns) gets a separate `iceberg_v3` flavor.
- **Override at non-leaf level.** Per-field overrides set the root target `TypeInstance` only; nested children (e.g. `array` element type) come from cast rules. Documented limitation.
- **Override of structural shape.** A source `array<X>` can be overridden to `list<Y>` (different element type via cast rules) but cannot be flattened to a scalar by override. Out of scope.

---

## 3. Data Model

No schema migration. All work uses existing tables: `DataType`, `CastRule`, `TypeInstance`, `Dataset` (`DatasetHive` polymorphic kind), `DatasetSchema`, `Field`, `FieldBinding`, `DatasetLink`, `FieldLink`, `TechFieldTemplate(Field)`. Two new seed YAMLs and one new seeder script — but no new model.

### 3.1 `CastRule` reuse — single table for two semantics

`CastRule` already references `DataType` rows from any flavor (no constraint that source and target share a flavor). The compatibility algorithm (Phase 3) already uses `CastRule` cross-flavor: when a `DatasetLink` pins a Postgres source schema to an Iceberg target schema, compat looks up `(source_dt, target_dt)` in `CastRule`.

Lake-sync uses the same table with a different lookup: given a source `DataType`, find rules where the target's flavor is `iceberg_v2`. The model already supports this; only the query path is new.

We deliberately do **not** add an `is_default` column or a separate `TypeMapping` entity. Rationale:

- Splitting forces the compat algorithm to consult two tables for cross-flavor links.
- The seed file (`casts_pg14_to_iceberg_v2.yaml`) defines exactly one default per `(source_dt, target_flavor)` pair. If an engineer later adds a second rule (for a non-default lake target type), lake-sync handles the ambiguity at runtime — see §4.3.
- The two semantics share shape: `(src_dt, tgt_dt, param_mapping JSONB, safety enum)`. Splitting would duplicate CRUD, indexes, and tests for a difference that is conceptual, not structural.

### 3.2 `iceberg_v2` flavor — type catalog

New `SystemKind` `hive` (HMS catalog) and new `SystemFlavor` `iceberg_v2` under it. The flavor is the format/spec; engines (Impala, Spark) consume the same Iceberg type set.

The catalog mirrors Apache Iceberg v2 primitives and nested types verbatim, sourced from the official spec (`format/spec.md`, version 2 section). Per the spec, v2 supports the following types — all v3 additions (`unknown`, `variant`, `geometry`, `geography`, `timestamp_ns`, `timestamptz_ns`) are intentionally excluded and would require an `iceberg_v3` flavor in a later phase.

**Primitive types** (14):

| Code | Params | Render template |
|---|---|---|
| `boolean`, `int`, `long`, `float`, `double` | none | identity |
| `decimal` | `precision: int (1..38)`, `scale: int (0..38)` | `decimal({precision},{scale})` |
| `date`, `time`, `timestamp`, `timestamptz` | none | identity (microsecond precision; v2 has no nanosecond variant) |
| `string`, `uuid`, `binary` | none | identity |
| `fixed` | `length: int (>=1)` | `fixed({length})` |

**Nested types** (3):

| Code | Slot convention | Render template |
|---|---|---|
| `list` | child slot `element` | `null` (not directly renderable) |
| `map` | child slots `key`, `value` | `null` |
| `struct` | child slot = struct field name | `null` |

(Nested-type render templates are `null` because rendering composes children, which is downstream of the type catalog. Lake-sync emits no DDL today, so no renderer is required.)

The seed file `backend/scripts/data/iceberg_v2.yaml` follows the same format as `postgres14.yaml` and is loaded via the existing `seed_data_types.py` script.

### 3.3 `param_mapping` mini-DSL

`CastRule.param_mapping` is JSONB that translates source-type parameters to target-type parameters. Phase 3's compat algorithm did not interpret it — only `safety` was read. Lake-sync introduces interpretation. The DSL is intentionally tiny:

| Mapping value | Semantics |
|---|---|
| `"@key"` | Pass-through: copy `src_params[key]` if present; drop the target key otherwise. |
| Literal scalar (`int`, `str`, `null`, `bool`) | Set the target param to the literal. |

Examples:

- `pg.numeric(P,S) → iceberg.decimal(P,S)` — `params: {precision: "@precision", scale: "@scale"}`.
- `pg.varchar(N) → iceberg.string` — `params: {}` (length dropped; Iceberg `string` is unbounded).
- `pg.bigint → iceberg.long` — `params: {}`.

Computed expressions (e.g. `bit_length / 8`) are out of scope. If an engineer needs that, they write a non-default `CastRule` row with hand-computed params and use the override mechanism to pick it for specific fields.

After applying the DSL, the resulting param dict is filtered against the target `DataType.params_schema` (existing `params_schema_validator` service): unknown keys are dropped, types are validated, missing required params trigger an error.

### 3.4 `Field.origin` for the target

- Mapped fields (mirror of source roots): `origin="mapped"`. Each requires an inbound `FieldLink` (Phase 3 invariant). Lake-sync creates them in step 7.
- Tech fields (from optional `tech_template_id`): `origin="tech"`. No `FieldLink`. Position assigned after all mapped fields.

### 3.5 `DatasetHive` for the target

Lake-sync writes a `DatasetHive` row with:

- `kind="hive"`, `system_id=request.target_system_id`, `layer=request.target_layer`.
- `object_name = f"{db_name}.{table_name}"` — two-part identity sufficient for HMS (no separate "schema" concept beyond `db`). The repo's convention for `Dataset.object_name` is "fully-qualified path components joined by dot, varying parts per kind"; RDBMS sources use `db.schema.table` or `schema.table`, Hive uses `db.table`.
- `db_name`, `table_name`, `catalog_uri` from request.
- `is_external` from request (default `True`).
- `file_format = "iceberg"` (hardcoded — this phase only creates Iceberg tables).
- `location`, `partition_cols` from request (optional).
- `serde`, `tblproperties`, `bkey_columns` left null in MVP.

---

## 4. Service & Algorithm

### 4.1 Endpoint

```
POST /api/v1/datasets/{source_dataset_id}/lake-sync
```

Body (`LakeSyncRequest`):

```python
class LakeSyncRequest(BaseModel):
    target_system_id: UUID
    target_layer: str
    db_name: str
    table_name: str
    catalog_uri: str
    location: str | None = None
    partition_cols: list[str] | None = None
    is_external: bool = True
    overrides: dict[str, FieldOverride] | None = None
    tech_template_id: UUID | None = None
    tech_overrides: list[TechFieldOverride] | None = None

class FieldOverride(BaseModel):
    data_type_code: str
    type_params: dict[str, Any] | None = None

# TechFieldOverride is the existing schema reused as-is.
```

Response (`LakeSyncResponse`):

```python
class LakeSyncResponse(BaseModel):
    target_dataset_id: UUID
    target_dataset_schema_id: UUID
    dataset_link_id: UUID
    mapped_field_count: int
    tech_field_count: int
    warnings: list[LakeSyncWarning]

class LakeSyncWarning(BaseModel):
    field_name: str
    code: str        # "UNSUPPORTED_TYPE_FALLBACK", "OVERRIDE_APPLIED"
    detail: str
```

Authorization: same auth-prefix as `POST /datasets/...`. The authenticated user's `id` is written to `created_by` on every new row.

### 4.2 Orchestration

`LakeSyncService.create_lake_target(uow, source_dataset_id, request, applier_id)` — one `async with uow:` block, atomic.

1. **Pre-flight validation.**
   - Resolve `source_dataset` (404 → `DATASET_NOT_FOUND`).
   - Resolve `source_schema` = latest non-orphan `DatasetSchema` for the source (orphan = no `FieldBinding` rows). If absent → `LAKE_SYNC_NO_SOURCE_SCHEMA`.
   - Resolve `target_system` (→ `SYSTEM_NOT_FOUND`) and its flavor (→ `SYSTEM_FLAVOR_NOT_FOUND`). Assert `flavor.code == "iceberg_v2"`; otherwise → `LAKE_SYNC_TARGET_FLAVOR_MISMATCH`.
   - Check no existing `DatasetHive` with `(target_system_id, db_name, table_name)`; otherwise → `DATASET_ALREADY_EXISTS`.
   - If `tech_template_id` present: resolve template (→ `TECH_FIELD_TEMPLATE_NOT_FOUND`), assert `template.layer == request.target_layer` (→ `TECH_FIELD_TEMPLATE_LAYER_MISMATCH`).
   - All `request.overrides` keys exist as root `Field.name` on `source_dataset`; otherwise → `LAKE_SYNC_UNKNOWN_OVERRIDE_FIELD`.
   - All override `data_type_code` values exist in `iceberg_v2`; otherwise → `DATA_TYPE_NOT_FOUND`.

2. **Create target `DatasetHive`.** Fields per §3.5.

3. **Create target `DatasetSchema v1`.** `version_num=1`, `dataset_id=target_dataset.id`.

4. **Mirror mapped fields.**
   - Eager-load source root `Field` rows + their `FieldBinding` for `source_schema.id` + `TypeInstance` tree + leaf `DataType`. Use `selectinload` to avoid `MissingGreenlet`.
   - For each source root `Field`, create target `Field(origin="mapped", name=src.name, path=None)`.
   - Resolve target `TypeInstance` tree for each via `resolve_target_ti(...)` (§4.3). Collect warnings; collect ambiguities. If any ambiguity is unresolved by override → fail-fast with `LAKE_SYNC_AMBIGUOUS_CAST` carrying `{field_name, candidate_data_type_codes}`.
   - Batch-create `TypeInstance` rows depth-first (same approach as `crawler/aide_crawler/applier.py:_batch_create_type_trees`, lifted into a backend helper `backend/services/type_instance_tree.py` for reuse).
   - Create `FieldBinding` rows: `position=src.position`, `is_nullable=src.is_nullable` (carried over verbatim — we do not tighten nullability in this phase), `dataset_schema_id=target_schema.id`.

5. **Tech fields (if `tech_template_id` set).**
   - Load template fields via `uow.tech_field_template_fields.list_by_template(template_id)`.
   - For each field `tf`:
     - `effective_type_code = tech_overrides[tf.name].type_code if overridden else tf.type_code`.
     - `data_type_code = tech_type_resolver.resolve("iceberg_v2", effective_type_code)`. If `None` → `TECH_TYPE_CODE_NOT_RESOLVABLE`.
     - Resolve `DataType` by `(iceberg_v2.id, data_type_code)`.
     - Create `Field(origin="tech")` with `position = mapped_field_count + tf.order`.
     - Create leaf `TypeInstance(params={})`.
     - Create `FieldBinding`. **No `FieldLink`** (origin=tech invariant).

6. **Create `DatasetLink`** with `(source_dataset_id, target_dataset_id, source_schema_id=source_schema.id, target_schema_id=target_schema.id)`. Existing `DatasetLinkService` invariants apply.

7. **Create `FieldLink` rows** for every mapped target field: `(source_field_id, target_field_id, dataset_link_id)`. Done after step 6 because `dataset_link_id` is required.

8. **Commit UoW.** Return `LakeSyncResponse`.

Any error at any step rolls back the entire transaction. Partial target chains are never observed.

### 4.3 Cast resolution algorithm

```python
def resolve_target_ti(
    src_ti: TypeInstance,
    target_flavor_id: UUID,
    field_override: FieldOverride | None,
    field_name: str,
    warnings: list[LakeSyncWarning],
) -> TargetTI:
    if field_override is not None:
        target_dt = lookup_dt(field_override.data_type_code, target_flavor_id)
        target_params = filter_against_schema(
            field_override.type_params or {}, target_dt.params_schema
        )
        warnings.append(LakeSyncWarning(
            field_name=field_name, code="OVERRIDE_APPLIED",
            detail=f"override → {target_dt.code}",
        ))
        return TargetTI(target_dt.id, target_params, children=[])

    rules = find_cast_rules(
        source_data_type_id=src_ti.data_type_id,
        target_flavor_id=target_flavor_id,
    )
    if len(rules) == 0:
        target_dt = lookup_dt("string", target_flavor_id)
        warnings.append(LakeSyncWarning(
            field_name=field_name, code="UNSUPPORTED_TYPE_FALLBACK",
            detail=f"no CastRule for {src_ti.data_type.code} → iceberg_v2; "
                   f"used 'string'",
        ))
        return TargetTI(target_dt.id, type_params={}, children=[])

    if len(rules) > 1:
        raise AppException(errors.LAKE_SYNC_AMBIGUOUS_CAST, details={
            "field": field_name,
            "candidates": [r.target.data_type_code for r in rules],
        })

    rule = rules[0]
    target_params = apply_param_mapping(rule.param_mapping, src_ti.type_params)
    target_params = filter_against_schema(target_params, rule.target.params_schema)

    children = [
        TargetTIChild(
            slot=child.slot,
            tree=resolve_target_ti(
                child.node, target_flavor_id,
                field_override=None,  # MVP: no nested overrides
                field_name=f"{field_name}.{child.slot}",
                warnings=warnings,
            ),
        )
        for child in src_ti.children
    ]
    return TargetTI(rule.target_data_type_id, target_params, children)


def apply_param_mapping(
    mapping: dict[str, Any], src_params: dict[str, Any]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, str) and value.startswith("@"):
            ref = value[1:]
            if ref in src_params:
                out[key] = src_params[ref]
            # else: drop the key (target param will use its own default)
        else:
            out[key] = value
    return out
```

**Slot convention bridging.** Source `pg14.array` uses child slot `item`; target `iceberg_v2.list` uses `element`. The recursion preserves source slot names by default. The mapping from `array` to `list` is a special case: when the target `data_type_code == "list"`, the helper rewrites the single child's slot from `item` to `element`. This is the only known cross-flavor slot rename in v2; documented in code as `_LIST_SLOT_RENAMES = {"item": "element"}` keyed by target type code.

### 4.4 Errors

New error codes added to `backend/core/errors.py`:

- `LAKE_SYNC_NO_SOURCE_SCHEMA` — 422 — source dataset has no `DatasetSchema` with `FieldBinding` rows.
- `LAKE_SYNC_TARGET_FLAVOR_MISMATCH` — 422 — target system's flavor is not `iceberg_v2`.
- `LAKE_SYNC_UNKNOWN_OVERRIDE_FIELD` — 422 — `overrides` references a field name absent from the source dataset's roots.
- `LAKE_SYNC_AMBIGUOUS_CAST` — 422 — multiple `CastRule` rows match `(source_dt, iceberg_v2)` for a field with no override. Response details include `{field, candidates}`.

Reused error codes: `DATASET_NOT_FOUND`, `DATASET_ALREADY_EXISTS`, `SYSTEM_NOT_FOUND`, `SYSTEM_FLAVOR_NOT_FOUND`, `DATA_TYPE_NOT_FOUND`, `TECH_FIELD_TEMPLATE_NOT_FOUND`, `TECH_FIELD_TEMPLATE_LAYER_MISMATCH`, `TECH_TYPE_CODE_NOT_RESOLVABLE`.

### 4.5 Idempotency

Re-invocation with the same `(target_system_id, db_name, table_name)` returns 409 `DATASET_ALREADY_EXISTS`. Re-run flow (delete and recreate, or evolve the existing target) is not implemented in this phase.

To recreate from scratch the engineer must, in order:

1. Delete the `DatasetLink` (its `source_schema_id` / `target_schema_id` FKs are `ON DELETE RESTRICT`, which would otherwise block the next step). `FieldLink`s cascade with the `DatasetLink`.
2. Delete the target `Dataset`. This cascades to `DatasetSchema`, `Field`, `FieldBinding`. `TypeInstance` rows do **not** cascade-delete (they were referenced by the now-gone `FieldBinding.type_instance_id` with CASCADE on the FK going the other way) — orphan `TypeInstance` rows are an existing repo behavior, not introduced by lake-sync, and may be cleaned up with a future maintenance task.
3. Re-invoke `lake-sync`.

Alternatively, evolve the existing target via the per-resource APIs (`DatasetSchema` bump, `FieldBinding` edits) — that path is unchanged from Phase 3.

---

## 5. Seeds and Catalog Provisioning

Three new artefacts under `backend/scripts/data/`:

### 5.1 `iceberg_v2.yaml`

Mirrors `postgres14.yaml` shape. Loaded via existing `seed_data_types.py`:

```
uv run python -m backend.scripts.seed_data_types \
    --file backend/scripts/data/iceberg_v2.yaml
```

Idempotent: re-running picks up additions to the YAML; removed entries are not deleted (FK protection via `TypeInstance`). Concrete content is the 14 primitives + 3 nested types per §3.2, sourced verbatim from the Apache Iceberg v2 spec.

### 5.2 `casts_pg14_to_iceberg_v2.yaml` and `seed_cast_rules.py`

New seeder script `backend/scripts/seed_cast_rules.py` modeled after `seed_data_types.py`. Format:

```yaml
mappings:
  - source: {flavor: postgres14, code: bigint}
    target: {flavor: iceberg_v2, code: long}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: integer}
    target: {flavor: iceberg_v2, code: int}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: smallint}
    target: {flavor: iceberg_v2, code: int}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: text}
    target: {flavor: iceberg_v2, code: string}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: varchar}
    target: {flavor: iceberg_v2, code: string}
    safety: safe
    params: {}
  - source: {flavor: postgres14, code: char}
    target: {flavor: iceberg_v2, code: string}
    safety: safe
    params: {}
  - source: {flavor: postgres14, code: numeric}
    target: {flavor: iceberg_v2, code: decimal}
    safety: safe
    params: {precision: "@precision", scale: "@scale"}
  - source: {flavor: postgres14, code: decimal}
    target: {flavor: iceberg_v2, code: decimal}
    safety: implicit
    params: {precision: "@precision", scale: "@scale"}
  - source: {flavor: postgres14, code: real}
    target: {flavor: iceberg_v2, code: float}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: double}
    target: {flavor: iceberg_v2, code: double}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: boolean}
    target: {flavor: iceberg_v2, code: boolean}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: uuid}
    target: {flavor: iceberg_v2, code: uuid}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: date}
    target: {flavor: iceberg_v2, code: date}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: time}
    target: {flavor: iceberg_v2, code: time}
    safety: safe
    params: {}
  - source: {flavor: postgres14, code: timestamp}
    target: {flavor: iceberg_v2, code: timestamp}
    safety: safe
    params: {}
  - source: {flavor: postgres14, code: timestamptz}
    target: {flavor: iceberg_v2, code: timestamptz}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: bytea}
    target: {flavor: iceberg_v2, code: binary}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: array}
    target: {flavor: iceberg_v2, code: list}
    safety: safe
    params: {}
  - source: {flavor: postgres14, code: json}
    target: {flavor: iceberg_v2, code: string}
    safety: unsafe
    params: {}
  - source: {flavor: postgres14, code: jsonb}
    target: {flavor: iceberg_v2, code: string}
    safety: unsafe
    params: {}
  - source: {flavor: postgres14, code: smallserial}
    target: {flavor: iceberg_v2, code: int}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: serial}
    target: {flavor: iceberg_v2, code: int}
    safety: implicit
    params: {}
  - source: {flavor: postgres14, code: bigserial}
    target: {flavor: iceberg_v2, code: long}
    safety: implicit
    params: {}
```

Types not listed (e.g. `tsvector`, `inet`, `xml`, range types, geometric types, network types, money) have no default rule. Lake-sync falls back to `string` with `UNSUPPORTED_TYPE_FALLBACK` warning. Engineers add explicit `CastRule` rows for those types as needed.

The seeder is idempotent: matched on `(source_data_type_id, target_data_type_id)`, updated in place when `safety` or `params` change. Loading fails fast on missing source or target `DataType` rows — types must be seeded first.

### 5.3 `tech_type_resolver.yaml` extension

Add an `iceberg_v2` branch covering all abstract `type_code`s used by existing templates (`scd2_core_v1`, `cdc_payload_kafka_v1`):

```yaml
- {flavor: iceberg_v2, type_code: TIMESTAMP, data_type_code: timestamp}
- {flavor: iceberg_v2, type_code: STRING,    data_type_code: string}
- {flavor: iceberg_v2, type_code: BIGINT,    data_type_code: long}
- {flavor: iceberg_v2, type_code: INTEGER,   data_type_code: int}
- {flavor: iceberg_v2, type_code: BOOLEAN,   data_type_code: boolean}
- {flavor: iceberg_v2, type_code: UUID,      data_type_code: uuid}
```

`tech_type_resolver.yaml` is **not** seeded into the DB — it is loaded at backend module-load time via `TechTypeResolver.from_yaml(...)` in `backend/services/dataset.py`. Therefore extending it takes effect only after the backend process restarts (Docker Compose restart of the `app` service). Adding new templates that introduce new abstract `type_code`s requires extending this map alongside `postgres14` and `iceberg_v2` branches together.

---

## 6. Layer Boundaries

**`LakeSyncService`** (`backend/services/lake_sync.py`) owns orchestration: validation, calling `resolve_target_ti`, batching `TypeInstance` writes, creating `FieldBinding`/`DatasetLink`/`FieldLink`. It does not own SQL — that lives in the existing repositories. It does not own DTOs — those re-export from `aide-schemas`.

**`backend/services/type_instance_tree.py`** is a new server-side helper that batch-writes a `TypeInstance` tree given a depth-flat plan, using `uow.session` directly. The crawler already has an SDK-based equivalent at `crawler/aide_crawler/applier.py:_batch_create_type_trees`; the two cannot share code (different transport — UoW vs HTTP), but they implement the same depth-first batching algorithm. Lifting this into a backend service avoids ad-hoc inline batching in `LakeSyncService` and keeps the algorithm reviewable in one place server-side.

**`resolve_target_ti`** is a pure function in `backend/services/lake_sync_resolver.py`. No DB calls — it takes pre-loaded `DataType.params_schema` and `CastRule` candidates and returns a target tree plan. Trivially unit-testable (mirrors how Phase 3's `compute_field_compat_issues` is structured).

**Endpoint** (`backend/api/v1/lake_sync.py`) is thin: parse request → call service → serialize response. Standard `get_filter_sort_dependency` is not used (no listing).

**SDK** (`sdk/aide_sdk/resources/lake_sync.py`) adds `LakeSyncResource.create(source_dataset_id, request) -> LakeSyncResponse`. One method.

---

## 7. Testing Strategy

| Layer | What |
|---|---|
| `tests/services/test_lake_sync_resolver.py` | Pure unit-tests for `resolve_target_ti` and `apply_param_mapping`. Cases: leaf passthrough; `numeric(p,s)→decimal(p,s)`; `array→list` with slot rename; multiple rules → `LAKE_SYNC_AMBIGUOUS_CAST`; zero rules → fallback `string` with warning; override applied → cast rules ignored; `param_mapping` literal vs `@ref` interpretation. |
| `tests/services/test_lake_sync_service.py` | Mocked UoW (`_MockUnitOfWork` pattern from `test_system_kind_service.py`). Cases: happy mapped-only; happy with `tech_template_id`; ambiguous cast with no override → error; unsupported type → string + warning; override on unknown field → error; flavor mismatch; existing target → 409; tech-template layer mismatch. |
| `tests/api/test_lake_sync.py` | `transactional_session` fixture. End-to-end: seed pg14 + iceberg_v2 + casts → create source dataset chain via repos → POST `/lake-sync` → assert target chain (`DatasetHive`, `DatasetSchema`, `Field`s with correct `origin`, `FieldBinding`s, `TypeInstance` tree, `DatasetLink`, `FieldLink`s 1:1 with mapped fields). |
| `tests/scripts/test_seed_cast_rules.py` | YAML loading, idempotency, error on missing `DataType`. |

After the phase, a third copy of `_create_dataset(...)`/`_create_field(...)` helpers may emerge in `tests/api/test_lake_sync.py` — at that point promote them to `tests/_helpers.py` per the existing CLAUDE.md guidance.

Run pattern: `PYTEST_ARGS="-v tests/api/test_lake_sync.py" make test-docker` for narrow scope; full suite via `make test-docker` before merging.

---

## 8. Lockstep Bumps

- **`aide-schemas`** — new DTOs (`LakeSyncRequest`, `LakeSyncResponse`, `LakeSyncWarning`, `FieldOverride`), new error codes. Major bump (CLAUDE.md policy: lockstep major on any breaking schema change; even though this is additive, we keep the chain coherent).
- **`backend`** — endpoint, service, resolver, seeder, seed YAMLs, error codes.
- **`aide-sdk`** — `LakeSyncResource`. Minor or major depending on SDK semver convention (currently lockstep major with schemas).
- **`aide-crawler`** — no changes this phase.

---

## 9. Migrations

Zero schema migrations. All work uses existing tables. Operator runbook (per-environment, one-time):

1. `uv run python -m backend.scripts.seed_data_types --file backend/scripts/data/iceberg_v2.yaml`
2. Restart the backend process (Docker Compose `app` service) so the extended `tech_type_resolver.yaml` is reloaded into memory. No DB seed is needed for the resolver — it is a module-load-time YAML.
3. `uv run python -m backend.scripts.seed_cast_rules --file backend/scripts/data/casts_pg14_to_iceberg_v2.yaml`
4. Create one or more lake `System` rows pointing at the `iceberg_v2` flavor (existing `POST /systems`).

After step 4, lake-sync is callable.

---

## 10. Documentation

- **`docs/integrations/lake-sync.md`** — engineer guide: pre-requisites, request body, override format, error semantics, sample SDK usage.
- **`docs/adr/adr-019-lake-sync.md`** — decisions: single `CastRule` table, `iceberg_v2` flavor, deferred DDL, override-as-leaf-only.
- **`docs/AIDE_data_model.json`** — no change (no new tables).
- **`CLAUDE.md` known quirks** to add:
  - Lake-sync atomic; partial target chains never observed.
  - `LAKE_SYNC_AMBIGUOUS_CAST` payload includes `candidates`; remediate via `overrides` request field.
  - Override is leaf-only. For `array`, override `data_type_code="list"` produces `list<source-resolved-element>`; child type cannot be overridden in MVP.
  - `tech_type_resolver.yaml` must include an `iceberg_v2` branch covering every abstract `type_code` referenced by templates; otherwise lake-sync with `tech_template_id` raises `TECH_TYPE_CODE_NOT_RESOLVABLE`.
  - Iceberg type catalog is canonical to Apache Iceberg v2 spec. v3-only types (`unknown`, `variant`, `geometry`, `geography`, `timestamp_ns`, `timestamptz_ns`) belong in a future `iceberg_v3` flavor, not this one.
  - Slot rename `array.item → list.element` is the only known cross-flavor slot rename in v2; lives in `_LIST_SLOT_RENAMES` constant in `lake_sync_resolver.py`.
