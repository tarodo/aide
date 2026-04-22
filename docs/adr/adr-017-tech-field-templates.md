# ADR-017: Tech-Field Templates — Detached Presets with Abstract Type Codes

**Status:** Accepted
**Date:** 2026-04-21
**Deciders:** Backend team lead

---

## 1. Context and Problem

Downstream datasets in AIDE routinely carry the same shape of *technical*
columns alongside their domain fields:

- **SCD2** overlays: `valid_from`, `valid_to`, `is_current`, `row_hash`.
- **CDC payload**: `cdc_op`, `cdc_ts`, `source_lsn`, `before_image`,
  `after_image`.
- **Snapshots**: `snapshot_at`, `snapshot_id`, `etl_run_id`.

Each of these sets repeats verbatim across every dataset that uses the
pattern. Before this ADR, the only way to materialize them was to type
each column by hand, per dataset, per flavor — error-prone,
inconsistent between datasets, and tedious at scale (hundreds of tables
in the catalogue).

Two constraints shape the design:

1. **Flavor independence at the template layer.** A single tech-field
   preset ("SCD2") must be reusable across Postgres, Iceberg, Kafka
   (Avro), and any future flavor without duplicating the preset.
   Flavor-specific concrete types (e.g. Postgres `TIMESTAMP WITH TIME
   ZONE` vs Avro `long (timestamp-millis)`) are resolved at apply-time,
   not encoded into the preset.
2. **Non-propagating apply semantics.** Applying a template materializes
   real `Field` rows on the target dataset; those rows then evolve with
   the dataset. Template edits must **not** retroactively rewrite
   already-applied fields — per-dataset drift is expected and operators
   must be free to tweak tech columns per dataset without the template
   fighting them on the next sync.

Phase 1 (ADR-016) already introduced `Field.is_tech` precisely to leave
room for this phase without reshaping the lineage tables; this ADR
fills in the template surface.

## 2. Options Considered

### Option A: Template with per-flavor copies

Store the template once per flavor combination: `scd2_postgres`,
`scd2_iceberg`, `scd2_kafka_avro`. Each copy pins concrete
`data_type_id` values.

**Pros:** No resolver layer; applying is a straight row copy; flavor
differences are explicit and auditable.

**Cons:** Duplicative — adding a new flavor means re-cutting every
template from scratch. Drift between copies is easy to miss and hard to
audit. Spec §3.7 D2 rejects this on the grounds that SCD2 is
semantically one preset, not N presets.

### Option B: Abstract `type_code` + flavor resolver (chosen, spec §3.7 D1)

Each `tech_field_template_fields` row stores an abstract type code
(`TIMESTAMP`, `STRING`, `BIGINT`, `JSONB`, …). At apply-time, a
resolver maps `(flavor, type_code) → data_type_code` using a
YAML-backed lookup table, and materializes the concrete `Field` +
`FieldBinding` rows.

**Pros:** One template covers all flavors. New flavors are added
purely in YAML — no schema change, no DB backfill, no template
rewrite. The set of abstract codes is small and stable (think Calcite
logical types), so the YAML stays readable.

**Cons:** Adds a resolver component and a YAML file to keep in sync
with new flavors. Two-layer naming (abstract code + concrete type)
requires operators to know the vocabulary.

### Option C: No templates — bind each dataset manually

Skip templates entirely; let dataset authors add tech fields one at a
time. Product requirement for reuse and bulk apply rejects this
outright.

## 3. Decision

Adopt Option B. Implementation details that must stay consistent
across model, service, resolver, and SDK:

- **Two tables:**
  - `tech_field_templates` — `MetaDataMixin` only (hard-delete; audit
    history for a preset is thin). Unique `code` (e.g.
    `scd2_overlay`). `layer` pins the template to a single
    `DatasetLayer` so applying to a mismatched dataset is blocked.
  - `tech_field_template_fields` — `MetaDataMixin` only;
    FK `template_id` with `ON DELETE CASCADE` (templates own their
    fields). Unique constraint `uq_tft_field_name` on
    `(template_id, name)` prevents duplicate column names inside one
    template. `order` drives deterministic apply ordering.

- **Detached apply.** `apply_tech_template(dataset_id, template_id,
  overrides)` creates `Field` rows with `is_tech=True` plus matching
  `FieldBinding` rows, but **no FK back to the template**. Once
  applied, the fields are owned by the dataset. Template edits do not
  propagate, by design — operators keep full control of per-dataset
  evolution.

- **`Field.extra` carries apply-time provenance.** Applied tech fields
  store `{"data_type_id": "<resolved>", "tech_type_code":
  "<abstract>"}` in the `extra` JSONB. Downstream `FieldBinding`
  creation reads the resolved `data_type_id` from this hint; the
  abstract code is retained for debug / UI display. This is a soft
  hint — not a validated FK — so schema evolution later can repoint
  the data type without migration pain.

- **Resolver is YAML-backed, module-scoped, frozen.** The resolver
  lives in `backend/scripts/data/tech_type_resolver.yaml` and is
  loaded **once at module import time** into a frozen dataclass
  wrapping `MappingProxyType`. Duplicate `(flavor, type_code)` entries
  fail loading (fail-fast at boot, never at apply-time). The mapping
  is read-only for the lifetime of the process.

- **Apply is idempotent and layer-gated.** If a field with the same
  name already exists on the target dataset, the apply skips it (no
  overwrite). If `dataset.layer != template.layer`, the apply rejects
  with 400 — templates are layer-specific because which tech columns
  make sense depends on the layer (e.g. CDC payload columns belong on
  `cdc` datasets, not `core`).

## 4. Consequences

**Positive:**

- Single template covers every flavor — no N-fold duplication for
  SCD2, CDC payload, snapshot, append_only.
- Applying is deterministic and side-effect-free beyond the field
  inserts; re-running does not double-create.
- Drift is allowed by design — operators customize per-dataset without
  the template fighting them back on the next sync.
- Adding a new flavor (e.g. Delta Lake) is a YAML-only change — no
  schema migration, no data backfill, no template rewrite.

**Negative:**

- Template changes do **not** propagate to already-applied fields.
  Teams that want the opposite semantics (sync-on-change) must
  re-apply explicitly; this is a deliberate trade-off against surprise
  rewrites.
- `tech_type_resolver.yaml` must be maintained alongside every new
  flavor or new abstract code; forgetting this is caught only when the
  first apply for that flavor runs.
- `Field.extra` is a soft hint, not a validated FK — a renamed or
  removed `data_type` will leave stale strings in `extra` until the
  field is re-applied.
- Module-level YAML load means malformed YAML breaks app boot. This
  is an intentional fail-fast: silent fallback to partial resolution
  would be worse.

**Migration:**

Purely additive — two new tables (`tech_field_templates`,
`tech_field_template_fields`), no changes to existing Phase 1 tables,
no data backfill. The `Field.extra` field already exists from Phase 1
and requires no change.

## 5. Related

- Spec: [`docs/superpowers/specs/2026-04-21-dataset-lineage-design.md`](../superpowers/specs/2026-04-21-dataset-lineage-design.md)
  §3.7 (template design), §5.3 (resolver contract), §8 (apply API).
- Phase 2 plan: [`docs/superpowers/plans/2026-04-21-dataset-lineage-phase-2.md`](../superpowers/plans/2026-04-21-dataset-lineage-phase-2.md)
- Phase 1 ADR: [`adr-016-dataset-lineage.md`](adr-016-dataset-lineage.md) —
  introduced `Field.is_tech`, which this ADR builds on.
- ADR-010: Enum as VARCHAR — `layer` and `type_code` follow this rule.
- ADR-011: YAML-Driven Reference Data Seeding — same pattern as the
  `tech_type_resolver.yaml` file.
