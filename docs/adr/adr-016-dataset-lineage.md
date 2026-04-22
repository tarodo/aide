# ADR-016: Dataset Lineage — Two-Level Link Model

**Status:** Accepted
**Date:** 2026-04-21
**Deciders:** Backend team lead

---

## 1. Context and Problem

AIDE describes how data flows from a source through a chain of layers
(source → CDC → Kafka → raw → core) before landing in analytical
storage. Pipelines routinely:

- copy one dataset into the next layer 1:1,
- unfold nested XML/JSON payloads into flat columnar targets,
- merge an archive snapshot with an "actual" feed into a single
  consolidated target,
- fan out one source column into several target columns inside one
  target dataset.

Before this ADR, the metastore described `Dataset` and `Field`
independently but had no way to express **which dataset feeds which**
(direction, cross-system, many-to-one merges) or **which source column
feeds which target column** (column-level lineage that analysts and
pipeline authors need). Without an explicit model we could only infer
lineage by guessing from naming conventions, which does not scale past
a dozen pipelines.

Two product constraints frame the design:

- **Only two transformations between layers are allowed**: (a) add
  technical fields (ingested_at, cdc_op, valid_from/valid_to, etl_hash,
  …), (b) drop fields. No expression-level transforms — no coalesce,
  case, concatenation, sql expressions. Every non-technical target
  column traces back to exactly one source column per incoming link;
  merges are modelled by multiple `dataset_link` rows ending on the
  same target.
- **Unfold** (nested `payload.customer.id` → flat `customer_id`) is
  carried by the existing `Field.parent_id` + `Field.path` hierarchy
  on the source side. A `field_link` stays a pure `(source, target)`
  reference; the `path` semantics live on the nested source leaf and
  do not leak into the link edge.

We need a persistence model that:

1. Makes dataset-level lineage a first-class query target (upstream /
   downstream subgraph for one dataset without reaggregating).
2. Preserves column-level granularity inside each dataset edge so
   unfold and merge remain expressible.
3. Enforces invariants that matter to product correctness (no self-
   link, non-technical target must have a source, target column has
   one source per link) either in the DB (where cheap) or in the
   service (where DB can't express it).
4. Leaves room for Phase 2 (tech-field templates) without reshaping
   the lineage tables.

## 2. Options Considered

### Option A: Field-level only

Persist only `field_link(source_field, target_field, note)`. Derive
the dataset-level edge on the fly via `DISTINCT
(source_field.dataset_id, target_field.dataset_id)`.

**Pros:** One table. No duplication of `(source_dataset, target_dataset)`
across every column edge.
**Cons:** Every dataset-level view (the common case for the catalogue
UI, graph walkers, delete-protection check) requires a `DISTINCT`-on-
aggregate query. Metadata that logically belongs to the **edge**
(note, soft-delete history, `row_version`, lifecycle actor) has no
natural home. Dataset-level invariants (layer monotonicity, no
self-link, uniqueness of an active pair) cannot be enforced by a DB
constraint because the edge is not materialized.

### Option B: Dataset-level only

Persist only `dataset_link(source_dataset, target_dataset)` with
enough metadata to describe the mapping in a blob.

**Pros:** Compact. Cheap to traverse the dataset graph.
**Cons:** Loses column-level granularity, which is exactly the part
that unfold + merge + fanout demand. A `dataset_link` blob that
encodes column mappings in JSONB would be validation-only-in-Python,
would not support FK-driven cascades when a Field is deleted, and
would reintroduce the same "no DB-level shape" problems ADR-010 flags
for enum values.

### Option C: Two-level link model — **chosen**

A parent `dataset_link` row owns the dataset-to-dataset edge; child
`field_link` rows, scoped by FK to their parent `dataset_link`,
describe the column mappings inside it.

- `dataset_link` is soft-delete (history matters for audit per
  ADR-006), has a partial unique index on `(source_dataset_id,
  target_dataset_id) WHERE deleted_at IS NULL`, and a
  `CheckConstraint` rejecting self-links.
- `field_link` is hard-delete; all three FKs (`dataset_link_id`,
  `source_field_id`, `target_field_id`) use `ON DELETE CASCADE` so
  removing a parent cleanly tears the children down.
- `field_link` has two unique constraints: `(dataset_link_id,
  source_field_id, target_field_id)` for "no duplicate triple" and
  `(dataset_link_id, target_field_id)` for "target column has ≤1
  source column within one link" — merges across `dataset_link` rows
  remain valid, fanout within a link remains valid.

**Pros:**

- Dataset-level queries ("what feeds `core.orders`?") hit one table.
- Column-level queries ("which source column produced this column?")
  hit one table joined to its parent.
- Edge metadata (soft-delete, `row_version`, note, actor columns)
  has a natural home on the parent row.
- FK cascades encode the "child is dead when parent is dead"
  invariant at the DB layer.
- Partial unique index enforces "one active edge per pair" without
  blocking historical rows.

**Cons:**

- Two tables to evolve and two services to keep in sync.
- Several invariants (layer monotonicity, non-tech-has-source,
  cross-dataset-id matching between link and its field_links) cannot
  be expressed in DDL and live in the service layer.

## 3. Decision

Adopt Option C. Implementation details that must stay consistent
across model, service, schema, and SDK:

- `DatasetLayer` is a Python `str, enum.Enum` (`source`, `cdc`,
  `kafka`, `raw`, `core`); stored as `VARCHAR` per ADR-010. A
  `LAYER_ORDER: dict[DatasetLayer, int]` maps each layer to a rank;
  the service rejects `dataset_link` create when
  `LAYER_ORDER[target.layer] <= LAYER_ORDER[source.layer]`. Strict
  monotonic order guarantees acyclicity without a cycle check, and
  allows skipping layers (SOURCE → RAW is fine).
- `DatasetPattern` is a Python enum (`scd1`, `scd2`, `snapshot`,
  `append_only`, `cdc_payload`, extensible). Stored on
  `Dataset.pattern_code` as `VARCHAR(32)`, nullable. Documents the
  pattern the target is materialized as; not every dataset has one.
- `Field.is_tech: Boolean NOT NULL DEFAULT false` distinguishes
  technical fields (added by the pipeline) from mapped fields. The
  rule "non-technical target must have ≥1 inbound `field_link`" is
  enforced by the service on `FieldLink.delete`, `Field.update`
  (setting `is_tech=False`), and is surfaced for newly-created fields
  via a deferred "unmapped fields" report rather than a create-time
  block.
- `dataset_link` uses `MetaDataMixin` + `SoftDeleteMetaDataMixin`
  (audit actors, soft-delete). `field_link` uses only
  `MetaDataMixin` — hard-delete with CASCADE on the three FKs does
  the right thing.
- `DatasetService.delete` blocks when the dataset has any active
  `dataset_link` as source or target (409 Conflict). Rationale:
  explicit unlink is safer than surprise cascade through a soft-
  deleted parent.
- Cross-system `dataset_link` is allowed and expected (source system
  Postgres → Kafka → raw lake → core lake is the common case).
- The source Field's `parent_id` + `path` carries unfold semantics.
  `field_link` stays a clean `(source_field_id, target_field_id,
  note)` edge; unfold information is **not** duplicated onto the
  link.
- Tech-field templates (`TechFieldTemplate`, `TechFieldTemplateField`
  + `apply_tech_template(dataset_id, template_id, overrides)`) are
  **not** in Phase 1 — they build on `Field.is_tech` and live in a
  separate plan. Deliberately, applied templates create real `Field`
  rows with `is_tech=True` but do **not** carry an FK back to the
  template — post-apply evolution is per-dataset, trading enforced
  consistency for operational flexibility.

## 4. Consequences

**Positive:**

- Dataset-level upstream/downstream traversal is a single table scan.
- Column-level lineage is FK-joined to its dataset edge, keeping
  unfold, merge, and fanout expressible.
- Fail-fast invariants: layer order + self-link CheckConstraint +
  partial unique active pair + target-in-link uniqueness + service-
  level "non-tech needs source" all block malformed lineage at
  write time.
- Cross-system edges and skipped layers are supported without special
  cases.

**Negative:**

- Two tables and two services add surface area vs. a single edge
  table. Most of that cost is paid once in Phase 1 scaffolding.
- Several invariants are service-enforced rather than DB-enforced
  (layer monotonicity, dataset-id matching between link and its
  field_links, non-tech-has-source at `is_tech=False` transitions).
  Integration tests are the safety net.
- `Field` delete hard-deletes its `field_link` rows via CASCADE;
  downstream non-tech target fields may become invalid and only
  surface the error on their next update — accepted as a mild
  cascade.

**Migration:**

Phase 1 is purely additive: two new columns
(`datasets.pattern_code`, `fields.is_tech` with `server_default="false"`)
and two new tables (`dataset_links`, `field_links`). No data backfill
beyond the `is_tech` server default. Existing datasets with
non-enum `layer` values continue to load; a one-time audit script
reports offenders before strict enum validation flips on.

## 5. Related

- Spec: [`docs/superpowers/specs/2026-04-21-dataset-lineage-design.md`](../superpowers/specs/2026-04-21-dataset-lineage-design.md)
- Phase 1 plan: [`docs/superpowers/plans/2026-04-21-dataset-lineage-phase-1.md`](../superpowers/plans/2026-04-21-dataset-lineage-phase-1.md)
- Phase 2 plan: tech-field templates (TBD — builds on `Field.is_tech`,
  does not modify Phase 1 tables).
- ADR-006: Soft-delete strategy — motivates `dataset_link`'s
  soft-delete + partial unique active-pair index.
- ADR-008: Polymorphic Dataset — downstream FKs on `datasets.id`
  continue to work because both `dataset_link` FKs target the parent
  table's id.
- ADR-010: Enum as VARCHAR — `DatasetLayer` and `DatasetPattern` both
  follow this rule.
