# Dataset Lineage — Design

**Date:** 2026-04-21
**Status:** Draft (awaiting review)
**Scope:** Add dataset-to-dataset and field-to-field linkage across layers (source → cdc → kafka → raw → core and XML/JSON unfold into Iceberg). Introduce technical-field tracking and pattern templates.

---

## 1. Context and Problem

AIDE's core purpose is to describe how data flows from a source through a chain of layers (source → cdc → kafka → raw → core) and ultimately lands in analytical storage (Iceberg on a data lake). Today the metastore knows about `Dataset` and `Field` entities, but has no way to express:

1. **Which dataset feeds which** across layers (1:1 copy, many-to-one merge, one-to-many fanout).
2. **Which source column feeds which target column** — the actual column-level lineage that analysts and pipeline authors need.
3. **Which target fields are "technical"** — added by the pipeline (ingested_at, cdc_op, valid_from/valid_to, etl_hash, etc.) as opposed to derived from a source column.
4. **Common technical-field presets** — SCD2 on a lake core layer adds one set of columns, a CDC payload on Kafka adds another. These are reusable but currently re-typed for every dataset.

Two constraints frame the design:

- **Only two transformations between layers are allowed**: (a) add technical fields, (b) drop fields. No expression-level transformations (no coalesce, case, concatenation, etc.). Every non-technical target column traces back to exactly one source column (per incoming `dataset_link`; merges use multiple `dataset_link` rows).
- **Unfold** (e.g. nested JSON `payload.customer.id` → flat Iceberg column `customer_id`) is modelled via the existing `Field.path` + `Field.parent_id` hierarchy on the source side. A `field_link` is always a clean `(source_field, target_field)` reference; `path` stays on the nested source leaf.

## 2. Goals / Non-Goals

**Goals:**

- Record explicit dataset-to-dataset links across layers with direction and cross-system support.
- Record column-to-column mappings inside each dataset link.
- Distinguish technical from mapped fields and enforce that every non-technical target field has at least one source mapping.
- Provide reusable tech-field templates keyed by layer (e.g. "SCD2 on CORE", "CDC payload on KAFKA") that seed, but do not own, real `Field` rows.
- Keep the model simple enough to evolve per-dataset without cascading template changes.

**Non-Goals:**

- Expression-level transformations (coalesce, case, sql expressions). Out of scope by product decision.
- Automatic lineage inference from SQL/ETL code. Lineage is authored explicitly.
- Time-travel over the lineage graph, or versioning beyond `row_version` optimistic locks.
- A generic "transform" entity with pluggable kinds. All links are 1:1 column copies (possibly through `path` on nested source).

---

## 3. Data Model

### 3.1 New enum: `DatasetLayer`

Stored as `varchar` per AIDE convention (CLAUDE.md, ADR-011); validated at the application level by a Python `str, enum.Enum`.

```python
class DatasetLayer(str, enum.Enum):
    SOURCE = "source"
    CDC = "cdc"
    KAFKA = "kafka"
    RAW = "raw"
    CORE = "core"


LAYER_ORDER: dict[DatasetLayer, int] = {
    DatasetLayer.SOURCE: 0,
    DatasetLayer.CDC: 1,
    DatasetLayer.KAFKA: 2,
    DatasetLayer.RAW: 3,
    DatasetLayer.CORE: 4,
}
```

Existing `Dataset.layer` column (`String(255)`, nullable, indexed) stays as-is at the DB level; validation is tightened at the schema/service layer. No data migration required unless existing values deviate from the enum; a one-time audit script should report offenders.

### 3.2 New enum: `DatasetPattern`

```python
class DatasetPattern(str, enum.Enum):
    SCD1 = "scd1"
    SCD2 = "scd2"
    SNAPSHOT = "snapshot"
    APPEND_ONLY = "append_only"
    CDC_PAYLOAD = "cdc_payload"
    # extend as needed
```

Added to `Dataset` as a nullable column. Not every dataset has a pattern (e.g. raw sources).

### 3.3 `Dataset` changes

```python
# backend/models/dataset.py
pattern_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
# layer column stays String(255); schema-level validation now uses DatasetLayer
```

No index on `pattern_code` initially — filter queries are rare; add later if needed.

### 3.4 `Field` changes

```python
# backend/models/field.py
is_tech: Mapped[bool] = mapped_column(
    Boolean, nullable=False, default=False, server_default="false"
)
```

Existing `path`, `parent_id`, `name`, uniqueness constraints stay. Unfold behaviour: a nested leaf Field has `parent_id` pointing to the root JSON/XML Field and a populated `path` (e.g. `$.payload.customer.id`); `field_link` references that leaf directly.

### 3.5 New table: `dataset_links`

```python
class DatasetLink(Base, MetaDataMixin, SoftDeleteMetaDataMixin):
    __tablename__ = "dataset_links"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    source_dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("datasets.id"), nullable=False, index=True
    )
    target_dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("datasets.id"), nullable=False, index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(default=1, nullable=False)

    source_dataset: Mapped["Dataset"] = relationship(foreign_keys=[source_dataset_id])
    target_dataset: Mapped["Dataset"] = relationship(foreign_keys=[target_dataset_id])
    field_links: Mapped[list["FieldLink"]] = relationship(
        back_populates="dataset_link",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "uq_dataset_link_pair_active",
            "source_dataset_id", "target_dataset_id",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        CheckConstraint(
            "source_dataset_id <> target_dataset_id",
            name="ck_dataset_link_no_self",
        ),
    )
```

Soft-delete per ADR-006 (history matters for audit). Unique partial index on active rows: one link per `(source, target)` among the living.

### 3.6 New table: `field_links`

```python
class FieldLink(Base, MetaDataMixin):
    __tablename__ = "field_links"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    dataset_link_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_links.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_field_id: Mapped[UUID] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    target_field_id: Mapped[UUID] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    note: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(default=1, nullable=False)

    dataset_link: Mapped[DatasetLink] = relationship(back_populates="field_links")

    __table_args__ = (
        UniqueConstraint(
            "dataset_link_id", "source_field_id", "target_field_id",
            name="uq_field_link_triple",
        ),
        UniqueConstraint(
            "dataset_link_id", "target_field_id",
            name="uq_field_link_target_in_link",
        ),
    )
```

Hard-delete only. `ON DELETE CASCADE` on all three FKs — cleanly unwind when parents disappear.

- `uq_field_link_triple` — no duplicate rows.
- `uq_field_link_target_in_link` — target column has ≤1 source column **within a given dataset_link** (merges live across multiple `dataset_link` rows, not within one).
- Source columns may appear multiple times (fanout: one source column → several target columns in the same link).

### 3.7 New tables: tech-field templates

```python
class TechFieldTemplate(Base, MetaDataMixin):
    __tablename__ = "tech_field_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    layer: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(default=1, nullable=False)

    fields: Mapped[list["TechFieldTemplateField"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TechFieldTemplateField.order",
    )


class TechFieldTemplateField(Base, MetaDataMixin):
    __tablename__ = "tech_field_template_fields"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("tech_field_templates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    order: Mapped[int] = mapped_column(nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)

    template: Mapped[TechFieldTemplate] = relationship(back_populates="fields")

    __table_args__ = (
        UniqueConstraint("template_id", "name", name="uq_tft_field_name"),
    )
```

Templates are a reference catalogue. Applying a template creates real `Field` rows with `is_tech=True`; after application, those Fields evolve independently (no FK from `Field` to the template). This enables one-dataset-at-a-time evolution when a preset changes — deliberate trade-off: flexibility over enforced consistency.

**`type_code` is abstract** (e.g. `TIMESTAMP`, `STRING`, `BIGINT`, `BOOLEAN`). At apply-time the service resolves `(type_code, dataset.flavor)` → concrete `data_type_id`. A resolver mapping (dict or small seed table) is needed; details below.

---

## 4. Validation Rules

### 4.1 `DatasetLinkService`

**On create:**

- `source_dataset` and `target_dataset` exist and are active (`deleted_at IS NULL`).
- `source_dataset_id != target_dataset_id` (belt + DB check constraint).
- `LAYER_ORDER[target.layer] > LAYER_ORDER[source.layer]` — strict monotonic order; skipping layers is allowed (SOURCE → RAW without CDC/KAFKA is fine). This also guarantees the graph is acyclic without an explicit cycle check.
- Cross-system links (`source.system_id != target.system_id`) are allowed.
- No active `DatasetLink` already exists for the `(source_id, target_id)` pair (409 Conflict).

**On delete:**

- Standard soft-delete. `field_links` cascade via the ORM relationship (hard-deleted).

### 4.2 `FieldLinkService`

**On create:**

- `dataset_link` exists and is active.
- `source_field.dataset_id == dataset_link.source_dataset_id`.
- `target_field.dataset_id == dataset_link.target_dataset_id`.
- `target_field` has no existing active `field_link` in this `dataset_link` (enforced by `uq_field_link_target_in_link`).
- Triple `(dataset_link_id, source_field_id, target_field_id)` unique (enforced by `uq_field_link_triple`).

**On delete:**

- If the removed row was the last incoming link for a non-technical `target_field`, return 409 "non-technical field must have at least one source mapping" (consistency check, not a DB constraint).

### 4.3 `DatasetService.delete` (extended)

- Reject delete (409) if the dataset has any active `dataset_link` as source or target. User must unlink first. Rationale: explicit state management over surprise cascade.

### 4.4 `FieldService` (extended)

- `update(is_tech=False)`: if the field has zero incoming active `field_link`, return 409.
- `delete`: soft on Dataset-level cascades through hard-delete here; `field_link` rows with this Field as source or target are removed by `ON DELETE CASCADE`. Downstream non-technical target fields may now fail validation on next update — accepted trade-off (mild cascade; user fixes when next touching the target).

### 4.5 Deferred validation for new non-technical fields

A newly-created `Field` with `is_tech=False` has no incoming links yet (it was just born). This is tolerated: validation is deferred and kicks in on `update(is_tech=False)` or when the dataset is "submitted" elsewhere. A reporting endpoint surfaces "unmapped" fields for UI warnings rather than blocking creation.

---

## 5. Services and API

### 5.1 Services (`backend/services/`)

- `dataset_link_service.py` — `GenericService[DatasetLink, Create, Update, Read]` plus the validations in §4.1.
- `field_link_service.py` — plus validations in §4.2 and a `bulk_create(dataset_link_id, items)` method.
- `tech_field_template_service.py` — CRUD.
- `dataset_service.py` — extended `delete` (block on active links), new `apply_tech_template(dataset_id, template_id, overrides)`.
- `field_service.py` — extended `update` and `delete` per §4.4.

### 5.2 API (`backend/api/v1/`)

```
POST   /api/v1/dataset-links/                          create
GET    /api/v1/dataset-links/                          list (filters: source, target)
GET    /api/v1/dataset-links/{id}                      detail (optional include=field_links)
PUT    /api/v1/dataset-links/{id}                      update note
DELETE /api/v1/dataset-links/{id}                      soft-delete

POST   /api/v1/dataset-links/{id}/field-links/         add mapping
POST   /api/v1/dataset-links/{id}/field-links/bulk     bulk add
GET    /api/v1/dataset-links/{id}/field-links/         list
PUT    /api/v1/field-links/{id}                        update note
DELETE /api/v1/field-links/{id}                        hard-delete

GET    /api/v1/datasets/{id}/upstream-links            links where dataset = target
GET    /api/v1/datasets/{id}/downstream-links          links where dataset = source
GET    /api/v1/datasets/{id}/unmapped-fields           non-tech fields lacking inbound links
POST   /api/v1/datasets/{id}/apply-tech-template       instantiate template fields

POST   /api/v1/tech-field-templates/                   CRUD templates
GET    /api/v1/tech-field-templates/
GET    /api/v1/tech-field-templates/{id}
PUT    /api/v1/tech-field-templates/{id}
DELETE /api/v1/tech-field-templates/{id}

POST   /api/v1/tech-field-templates/{id}/fields        CRUD preset fields
GET    /api/v1/tech-field-templates/{id}/fields
PUT    /api/v1/tech-field-template-fields/{id}
DELETE /api/v1/tech-field-template-fields/{id}
```

### 5.3 Apply-template workflow

`POST /api/v1/datasets/{id}/apply-tech-template` body: `{template_id: UUID, overrides?: [{name, type_code?, order?}]}`.

Service logic:

1. Load dataset and template. Verify `dataset.layer == template.layer` (400 otherwise).
2. For each `template_field`:
   - Resolve `type_code` → `data_type_id` via `(dataset.flavor, type_code)` lookup (resolver mapping maintained in `backend/core/tech_type_resolver.py` or similar; values live in a seed YAML).
   - If a `Field` with the same name already exists on the dataset, skip (no overwrite).
   - Otherwise create `Field(dataset_id, name, data_type_id, is_tech=True)`.
3. Return the list of created fields.

Templates can be applied multiple times; the operation is idempotent (skips existing names). `overrides` let the caller tweak order/type on the fly without editing the template.

### 5.4 Schemas (`schemas/aide_schemas/`)

New: `dataset_link.py`, `field_link.py`, `tech_field_template.py`, `tech_field_template_field.py`.

Extend: `dataset.py` (+ `pattern_code`, `layer` typed as `DatasetLayer`), `field.py` (+ `is_tech`).

Re-export from `backend/schemas/` for backward compatibility.

---

## 6. Migrations

Each Alembic migration is one focused step (per CLAUDE.md convention — strip unrelated ops):

1. `add_pattern_code_to_datasets` — nullable column, no data.
2. `add_is_tech_to_fields` — not-null with `server_default='false'`, backfills existing rows to `False`.
3. `create_dataset_links` — table + partial unique index + check constraint.
4. `create_field_links` — table + unique constraints.
5. `create_tech_field_templates` — table.
6. `create_tech_field_template_fields` — table.

**Seed:** `backend/scripts/seed_tech_templates.py` + `backend/scripts/data/tech_templates.yaml`. Idempotent (upsert by `code`, analogous to data-type seeding). Removing an entry from YAML does NOT delete DB rows (protects any user-applied references implicitly via application state).

**Data-model doc:** update `docs/AIDE_data_model.json` (ChartDB format) to include the new tables and FKs.

**ADR:** add `docs/adr/adr-016-dataset-lineage.md`, status Accepted, covering:

- Two-level lineage (dataset_link + field_link).
- Layer-order validation as the cycle-prevention mechanism.
- Delete blocking vs cascade on Dataset with active links.
- Detached template model (no FK from `Field` to template).
- Abstract `type_code` in template (option D1).

---

## 7. Testing

Mirror existing structure under `tests/`:

- `tests/models/test_dataset_link.py`, `tests/models/test_field_link.py` — ORM constraints (unique partial index, CASCADE, CheckConstraint).
- `tests/repositories/test_dataset_link_repository.py`, `tests/repositories/test_field_link_repository.py` — generic CRUD + filters.
- `tests/services/test_dataset_link_service.py` — all §4.1 validations (layer order, cross-system allowed, self-link rejected, uniqueness among active, block delete on referenced dataset).
- `tests/services/test_field_link_service.py` — §4.2 validations (dataset_id matching, target exclusivity inside link, fanout allowed, triple uniqueness).
- `tests/services/test_field_service.py` — extensions: `is_tech=False` requires inbound link, delete cascade semantics.
- `tests/services/test_dataset_service.py` — extensions: delete blocked when linked, `apply_tech_template` happy path + layer mismatch + existing-name skip + flavour resolve failure.
- `tests/services/test_tech_field_template_service.py` — CRUD.
- `tests/api/test_dataset_links.py`, `tests/api/test_field_links.py`, `tests/api/test_tech_field_templates.py` — endpoint contracts, permission, error codes.

Service tests use mocked UoW (see `_MockUnitOfWork` in `tests/services/test_system_kind_service.py`). API + repository tests use `transactional_session` fixture.

---

## 8. Phasing

The feature is large. Split into two implementation plans inside this single spec:

- **Phase 1 — core lineage (MVP):** `is_tech` on Field, `pattern_code` on Dataset, `DatasetLayer` enum, `dataset_link` + `field_link` with full validations, API endpoints for links and lineage queries. Delivers everything except templates.
- **Phase 2 — templates:** `tech_field_template*` tables, `apply_tech_template` endpoint, seed YAML, `type_code` resolver.

Each phase builds, tests, and ships independently; Phase 2 depends on Phase 1's `is_tech` column but nothing else.

---

## 9. Open Items / Deferred

- **`type_code` resolver details.** Phase 2 work item: define the mapping format (likely `backend/scripts/data/tech_type_resolver.yaml` listing `{flavor, type_code, data_type_code}` triples) and whether it lives as a seed table or a constant dict. Low risk — table can always be added later.
- **`pattern_code` enum membership.** Initial values listed in §3.2; expand as new patterns surface. No DB constraint, so extension is additive.
- **UI for lineage graph view.** Not part of this spec. Backend exposes upstream/downstream endpoints; the frontend is a separate project.
- **Audit script for existing `Dataset.layer` values.** Verify all current values belong to `DatasetLayer` enum before Phase 1 ship; fix outliers by hand (expected to be few).

---

## 10. Decision Summary (reference)

| # | Decision | Alternative considered |
|---|----------|------------------------|
| 1 | Both `dataset_link` and `field_link` tables | Field-level only (derived dataset relation) |
| 2 | `DatasetLayer` as Python str-enum | Layer entity table |
| 3 | `Field.is_tech` bool + strict validation | Derived tech from absence of links |
| 4 | `field_link` child of `dataset_link` (FK) | Independent field-level linkage |
| 5 | Layer order: strictly increasing, skipping allowed | Strict adjacency / unconstrained |
| 6 | Cross-system links allowed | Same-system only |
| 7 | No explicit DAG cycle check (layer order suffices) | Graph traversal on create |
| 8 | `(source, target)` unique among active | Multiple links per pair |
| 9 | No `transform_kind` on `dataset_link` | Enum `{copy, unfold, merge, fanout}` |
| 10 | `path` on source `Field` (via `parent_id` leaves) | `path` on `field_link` |
| 11 | Target field unique in a link; source may repeat (fanout) | Both unique |
| 12 | `dataset_link` soft-delete | Hard-delete |
| 13 | `field_link` hard-delete | Soft-delete |
| 14 | Block Dataset delete if links exist | Cascade soft-delete |
| 15 | `ON DELETE CASCADE` on `field_link` FKs | RESTRICT + explicit cleanup |
| 16 | Templates detached from `Field` (no FK) | `template_id` FK on `Field` |
| 17 | Abstract `type_code` in template (resolve per flavor) | Per-flavor template or no type |
| 18 | Deferred validation for newly-created non-tech Field | Two-phase create with links |
