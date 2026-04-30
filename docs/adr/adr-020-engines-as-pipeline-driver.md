# ADR-020: Engines as Pipeline-Driver Entity

**Status:** Accepted
**Date:** 2026-04-30
**Deciders:** Backend team lead

---

## 1. Context and Problem

Two operator pains motivate this phase.

First, every Spark or Impala job that moved data over a pinned
`DatasetLink` was hand-written. The metastore already knows the
source dataset, the target dataset, both pinned schemas, and the
field-level cast plan; yet it could not emit a `SELECT` / `INSERT`
skeleton over that contract. Engineers re-typed the same column
list, the same casts, and the same target table reference for every
new pipeline.

Second, when an RDBMS is mirrored to Kafka through Debezium or
Oracle GoldenGate, downstream consumers must understand the *envelope*
the CDC tool wraps around the row. Debezium's
`{before, after, op, ts_ms}` shape and OGG's distinct shape are not
interchangeable, and a Spark/Impala consumer that reads a CDC topic
cannot extract the real columns without that knowledge. That
knowledge was tribal — encoded in runbooks and engineer memory, not
in the metastore.

ADR-019 (Lake-Sync) explicitly deferred engine concerns:
"engine-specific concerns (DDL dialect, runtime config) belong in a
later phase." This ADR opens that phase.

Both pains are properties of a **pipeline hop**: which tool drives
the hop, and how that tool shapes the bytes flowing through it. The
natural attachment point is `DatasetLink` — the metastore's existing
representation of one hop.

## 2. Decisions

### 2.1 Polymorphic `Engine` over flat-with-JSONB

`Engine` is modelled as a joined-inheritance hierarchy: a base
`engines` table (`id`, `code`, `name`, `kind`, `role`, `version`,
audit columns, `row_version`, soft-delete) plus four subtype tables
that hold strongly-typed engine-specific columns:

- `engine_debezium`, `engine_ogg` — CDC engines: `envelope_template`
  (JSONB, NOT NULL) and `topic_routing` (JSONB, NULL).
- `engine_spark`, `engine_impala` — compute engines: `runtime_opts`
  (JSONB, NULL).

`role` is constrained to `cdc` or `compute` at the DB level
(`ck_engines_role`). The compatibility matrix between role and
`DatasetLink` shape is enforced in the service layer.

**Alternative rejected:** a flat `engines` table with a `kind: str`
discriminator and an everything-in-`config: JSONB` column. That
shape loses DB-level type discipline (envelope vs runtime opts are
structurally different and live next to each other in the same
column), pushes all per-kind validation into Pydantic, and makes
migration history opaque — a future change to the CDC envelope shape
is invisible to anyone reading the schema.

This mirrors the existing `Dataset` polymorphic pattern (ADR-008):
operators learn one mental model for "metadata entities with
sub-types".

### 2.2 FK on `DatasetLink` (one-to-one) over a junction table

`dataset_links.engine_id` is a nullable FK to `engines.id` with
`ondelete=RESTRICT`. One link binds to at most one engine. The
compatibility matrix is hardcoded in the service layer:

- CDC engines (`debezium`, `ogg`) attach only to RDBMS → Kafka
  links.
- Compute engines (`spark`, `impala`) attach only to Kafka → Hive
  or Hive → Hive links.

Other shapes are rejected with `ENGINE_INCOMPATIBLE_LINK`.

`RESTRICT` rather than `SET NULL`: deleting an engine that is still
attached must require explicit detach via
`PATCH /dataset-links/{id}` first (`ENGINE_IN_USE`). Silently
nulling the FK would lose the operator's intent.

**Alternative rejected:** a `dataset_link_engines` junction table
allowing many engines per hop (e.g. one CDC engine and one compute
engine on the same logical link). No concrete use case today; YAGNI.
Should a future shape demand it, migrating from a one-to-one FK to a
junction is mechanical.

### 2.3 Engine = pure transformation metadata, no credentials

`Engine` carries only the metadata needed to *describe* and
*render*: envelope shape (CDC) or dialect-relevant runtime opts
(compute). It does not carry connection strings, credential
references, or anything environment-bound. There is no
`credential_ref_id` on `engines`.

The orchestrator (Airflow, dbt, in-house scheduler) owns runtime
configuration. AIDE answers "what does the SQL look like?" and
"what does the CDC envelope look like?"; it does not answer "where
does this run and with whose credentials?"

**Alternative rejected:** add `credential_ref_id` now, leveraging
`CredentialRef` (ADR-013). Premature: the metastore has no
execution layer, and credentials would imply environment-bound
semantics on what is otherwise a pure metadata entity. The same
engine row is meant to be reusable across dev/prod environments;
binding credentials to it would force per-environment duplication.
Adding `credential_ref_id` later is non-breaking when an execution
layer arrives.

### 2.4 Deferred — auto-provisioning of Kafka chains and DDL emission

This phase ships:

- `Engine` entity (base + four subtypes) with full CRUD.
- Attach via `PATCH /dataset-links/{id}` (`engine_id` field).
- Synchronous `POST /dataset-links/{id}/render-sql` returning SQL
  text only — no side effects, no persistence.

Out of scope for this phase, intentionally:

- `POST /dataset-links/{id}/cdc-sync` — auto-creating the target
  Kafka chain whose schema mirrors the source RDBMS columns wrapped
  in the CDC engine's envelope template. Symmetric to `lake-sync`
  for the CDC case.
- DDL emission alongside SQL. `CREATE TABLE` is an
  engine × layer matrix (Impala vs Spark dialect, raw vs core vs
  mart conventions) and deserves its own ADR.
- Persisted render history. `render-sql` is stateless today; an
  audit trail of generated SQL versions is a separate concern.
- Execution / orchestrator integration. AIDE remains a metadata
  service.
- Engine flavor catalog. `version` is a `Literal[...]` whitelist in
  the Pydantic schemas; new versions require a one-line code edit
  per kind. A YAML-seeded catalog (analogous to
  `SystemFlavor` / `DataType`) is the deferred escape hatch.

## 3. Consequences

**Positive:**

- The most repetitive operator workflow — handwritten Spark SQL
  over a pinned link — collapses to a single API call. The
  metastore now answers a question it already had all the
  information for.
- CDC envelope knowledge becomes first-class metadata. Downstream
  renderers consume `envelope_template` deterministically; the
  envelope stops being tribal.
- Future `cdc-sync` and DDL phases inherit the entity model. No
  breaking changes to `Engine` are anticipated; new endpoints can
  be added without re-litigating the schema shape.
- The polymorphic pattern (ADR-008) is reused, so operators reading
  the schema for the first time recognise the layout.

**Negative:**

- `ENGINE_IN_USE` requires manual detach (`PATCH /dataset-links/{id}`
  with `engine_id: null`) before delete. Acceptable cost: the
  alternative is silent FK nulling, which would lose intent.
- Render is stateless; there is no audit trail of generated SQL
  versions. If reproducibility of "what SQL did we ship on date X"
  becomes a requirement, a render history table can be added.
- The compatibility matrix is hardcoded (three entries today: CDC →
  rdbms→kafka, compute → kafka→hive, compute → hive→hive). New
  pipeline shapes require code edits, not config.

**Neutral:**

- `version` whitelist (`Literal[...]`) is sharp-edged when a new
  Debezium / Spark version lands but the change is one line per
  kind in the Pydantic schemas. Engine flavor catalog is the
  deferred escape hatch when the maintenance cost stops being
  trivial.
- The `engine_id` FK is nullable. A `DatasetLink` without an engine
  is still a valid pinned hop — engines opt in.

## 4. Related ADRs

- ADR-008 (polymorphic Dataset) — the joined-inheritance pattern
  reused here for `Engine`.
- ADR-010 (enum-as-varchar) — `Engine.role` (`cdc` / `compute`)
  and `Engine.kind` (`debezium` / `ogg` / `spark` / `impala`) follow
  this rule.
- ADR-016 (two-level lineage) — provides the `DatasetLink` shape
  the engine FK pins to.
- ADR-018 (schema-pinned lineage) — provides the
  `source_schema_id` / `target_schema_id` contract that
  `render-sql` reads to materialise the column list.
- ADR-019 (lake-sync) — explicitly deferred engine concerns; this
  ADR opens that phase and reuses the same pinned-schema substrate.
