# ADR-019: Lake-Sync — Provisioning Lake Targets from Source Datasets

**Status:** Accepted
**Date:** 2026-04-27
**Deciders:** Backend team lead

---

## 1. Context and Problem

After Phase 3 (ADR-018) shipped schema-pinned lineage, AIDE could
describe a source-to-target contract but could not create the target
chain itself. Engineers built lake target tables by hand: pick a name,
choose every column type, write `Field` / `FieldBinding` /
`TypeInstance` rows, then create the `DatasetLink`. This is repetitive,
error-prone, and disconnected from the type catalog the metastore
already knows.

The goal of this phase is one backend call: given a source dataset and
a target lake system, produce the full target chain plus a pinned
`DatasetLink`, picking lake types from default rules and accepting
per-field overrides.

The lake stack is fixed for this phase: Apache Iceberg v2 (Parquet
under the hood) on Hive Metastore. Engines (Impala, Spark) read these
tables but are irrelevant to the metastore — engine-specific concerns
(DDL dialect, runtime config) belong in a later phase.

## 2. Decision

### 2.1 One `CastRule` table for both compatibility and provisioning

Reuse the existing `CastRule` table for both schema-evolution
compatibility (Phase 3 — ADR-018 §3.1) and source-to-lake type
translation (this phase). One table, two query lenses.

`DataType` is already flavor-scoped; `CastRule` already references it
cross-flavor (no constraint that `source.flavor == target.flavor`).
The compat algorithm already operates cross-flavor when a `DatasetLink`
pins a Postgres source schema to an Iceberg target schema. Lake-sync
adds a different lookup path — given a source `DataType`, find rules
where the target's flavor is `iceberg_v2` — but reads the same rows.

**Alternative rejected:** split into `CastRule` (intra-flavor) and a
new `TypeMapping` (cross-flavor). Splitting forces the compat
algorithm to consult two tables for cross-flavor links, doubles the
CRUD surface, and creates two seed pipelines for what is conceptually
one rule shape (`source_dt → target_dt`, `param_mapping`, `safety`).
The conceptual difference is a query lens, not a schema lens.

Ambiguity (more than one rule matches `(source_dt, target_flavor)`) is
resolved at runtime: lake-sync raises `LAKE_SYNC_AMBIGUOUS_CAST` with
`details={field, candidates}`; the operator disambiguates via per-field
overrides in the request.

### 2.2 Single `iceberg_v2` flavor under a new `hive` `SystemKind`

Register `SystemKind=hive` (HMS catalog) and `SystemFlavor=iceberg_v2`
(format spec). The flavor is the format/spec; engines (Impala, Spark)
consume the same Iceberg type catalog. Engine differences are presentation
concerns and belong in DDL render (deferred).

**Alternative rejected:** separate `impala` / `spark` flavors. Iceberg
v2 is one logical type system; engines read it identically. Splitting
flavors would duplicate the type catalog and force every cast rule and
tech-field-resolver mapping to be cloned per engine. The engine choice
is at *DDL render* time, not at *type resolution* time.

v3-only types (`unknown`, `variant`, `geometry`, `geography`,
`timestamp_ns`, `timestamptz_ns`) are intentionally excluded from
`iceberg_v2`. They belong in a future `iceberg_v3` flavor.

### 2.3 Defer DDL emission

This release is metastore-only. The endpoint creates AIDE entities and
returns ids and warnings; it does not produce a `CREATE TABLE` string.

**Alternative rejected:** emit DDL alongside the metastore writes. DDL
depends on engine (Impala vs Spark dialect) and layer (raw / core /
mart conventions). Picking one in this phase would force a wider
rewrite the moment a second engine or layer pattern lands. Deferring
keeps lake-sync sharply scoped — "metastore is the contract".

A future phase will add DDL renderers per (engine × layer) pair, all
fed by the same metastore state lake-sync produces here.

### 2.4 Per-field overrides apply at the leaf only

`request.overrides[field_name]` sets the root target `TypeInstance`
only. For `array<X>` source, override `data_type_code: "list"` produces
`list<X-resolved>` — the inner element comes from the source-resolved
cast rule, not from a nested override.

**Alternative rejected:** structured overrides that mirror the source
tree shape (`{"data_type_code": "list", "children": {"element": {...}}}`).
Nested overrides multiply the schema surface for an MVP feature whose
real use case is "pick an alternative leaf type for one column"
(typically `numeric → string` to escape decimal precision constraints).
A leaf-only override is enough to disambiguate the ambiguous-cast case
the runtime is designed to surface.

## 3. Consequences

**Positive:**

- One repetitive operator workflow becomes a single API call.
- Type catalog and cast rules become operationally visible — the
  metastore tells you what it can and cannot map, with severity.
- The same `CastRule` rows feed both the `dataset_link/compat` report
  and lake-sync resolution; engineers learn one mental model.
- DDL deferral keeps the surface tight; the next phase can iterate on
  engine/layer DDL without re-litigating type semantics.

**Negative:**

- `LAKE_SYNC_AMBIGUOUS_CAST` requires the operator to pick — there is
  no auto-resolution heuristic. Acceptable: "explicit failure" beats
  "wrong default."
- Re-running lake-sync requires manual cleanup (delete `DatasetLink`,
  then delete target `Dataset`). No idempotency-key support in MVP.
- Source-side `TypeInstance` trees deeper than 3 levels currently
  trigger `MissingGreenlet` because the eager-load chain is depth-3.
  Acceptable for current sources (depth ≤ 2). A future deepening
  refactor (recursive eager-load or CTE) is required if nested types
  reach depth-4+.

**Neutral:**

- The `iceberg_v2` flavor and `casts_pg14_to_iceberg_v2.yaml` are seed-
  only artefacts. Adding a new source flavor (`mysql8`, `oracle19`)
  means a new cast-rules YAML; no code change.

## 4. Related ADRs

- ADR-008 (polymorphic Dataset) — `DatasetHive` is the target row.
- ADR-010 (enum-as-varchar) — `Field.origin`, `CastSafety` are varchars.
- ADR-016 (two-level lineage) — provides the `DatasetLink`/`FieldLink`
  shape this phase pins schemas onto.
- ADR-017 (tech-field templates) — optional `tech_template_id` reuses
  this resolver.
- ADR-018 (schema-pinned lineage) — provides `Field.origin` and the
  schema-pin contract that lake-sync writes to.
