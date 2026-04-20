# ADR-008: Polymorphic Dataset — Joined Table Inheritance

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

A `Dataset` in AIDE represents a real piece of data living in some
external system: an RDBMS table, a Kafka topic, a blob-storage path,
an SFTP archive, a Hive table. These share common metadata —
`system_id`, `object_name`, `layer`, tags, extras, lineage, audit
columns — but each kind has its own required technical fields:

- RDBMS: catalog, schema, table name, PK columns, uniques.
- Kafka: topic, format, partitions, retention, key columns.
- Blob storage: path, file format, compression, partitioning.
- SFTP: path, format, compression, archive name.
- Hive: catalog URI, db, table, external flag, SerDe, tbl properties.

The crawler produces these as distinct artefacts; the SDK must
deserialize each one into a type-safe client object; admins browse,
filter, and update them through a single collection-style API.

We need a persistence + schema design that:

1. Keeps the common columns in one place (indexed uniqueness on
   `(system_id, object_name)`, soft-delete, optimistic-lock
   `row_version`).
2. Strongly types the kind-specific fields at the Python layer —
   schema, model, and SDK — so `DatasetKafka.partitions` is a real `int`
   and not a `dict[str, Any]` blob.
3. Lets callers add a new kind (e.g. `DatasetIceberg`) without
   rewriting the service, repository, or router for every existing kind.
4. Interacts cleanly with the soft-delete strategy (ADR-006) and the
   optimistic-lock strategy (ADR-009).

## 2. Options Considered

### Option A: SQLAlchemy joined-table inheritance + Pydantic discriminated union — **chosen**

- One `datasets` table for the common columns plus a discriminator
  column `kind`.
- One child table per kind (`dataset_rdbms`, `dataset_kafka`,
  `dataset_storage`, `dataset_sftp`, `dataset_hive`), sharing the
  parent's primary key via `ForeignKey("datasets.id")`.
- SQLAlchemy `__mapper_args__`:
  - Parent: `polymorphic_on="kind", polymorphic_identity="dataset"`.
  - Each child: `polymorphic_identity="<kind>"`.
- Pydantic schemas mirror the structure with per-kind `Create`, `Read`,
  `Update` classes tagged by `kind: Literal["<kind>"]`, unified as
  `AnyDatasetCreate / AnyDatasetRead / AnyDatasetUpdate` discriminated
  unions using `Annotated[Union[...], Field(discriminator="kind")]`.

| Dimension | Assessment |
|-----------|------------|
| Type safety (Python side) | **High** — each kind is its own class |
| Schema normalization | **High** — per-kind columns carry their own types + constraints |
| Query simplicity for common list | **Good** — a single `SELECT ... FROM datasets WHERE ...` works |
| Cost of adding a kind | **Medium** — new table + migration + schemas + MODEL_MAP entry |
| FK targets from children | **Natural** — Field, DatasetSchema, FieldBinding FK the parent `datasets` row |

**Pros:**

- Common columns are normalized and indexed once. The unique index on
  `(system_id, object_name)` with `WHERE deleted_at IS NULL` works for
  every kind.
- Kind-specific columns get proper types (`ARRAY(String)`, `JSONB`,
  `Integer`, `BigInteger`), not type-erased `JSONB` blobs.
- `SELECT` for a list view touches only the parent table — cheap for
  catalogue browsing where clients often do not need kind-specific
  details.
- A single "is this object already registered?" query (ADR-001's
  `_pre_create` dup check) works for every kind without a union.
- Child tables cascade-join automatically when SQLAlchemy loads a
  `DatasetKafka` by id — no extra session gymnastics.

**Cons:**

- Reading full details for a large list requires per-kind joins (SA
  handles this on-demand, but it is N+1 unless batched via
  `polymorphic_load="selectin"`).
- The generic `GenericService` / `SoftDeleteService` base (ADR-002)
  does not fit as-is — `DatasetService` overrides
  `create / get_by_id / get_paginated / update / delete / restore`
  to dispatch on `kind`.
- Two sources of truth for the kind list: the SQLAlchemy subclasses
  and the Pydantic union members. Both must be extended when a new
  kind arrives, and the `kind` string must match at every point.

### Option B: Single table inheritance (`single_table`)

One `datasets` table with a `kind` column and a nullable column per
kind-specific field.

**Pros:** no joins; simplest SQL.
**Cons:** a single wide table with N \* k nullable columns (~30 as of
today); no DB-level NOT NULL on kind-specific required fields; every
kind addition widens the table; `ARRAY(String)` / `JSONB` blocks
eventually collide on naming.

### Option C: Concrete table inheritance (no shared parent)

Separate `datasets_rdbms`, `datasets_kafka`, ... tables, each with its
own copy of the common columns. No shared parent table.

**Pros:** highest isolation per kind.
**Cons:** every foreign key target (Field, DatasetSchema, FieldBinding)
must point to the right kind's table; cross-kind list queries require
`UNION ALL` over five tables; the uniqueness constraint `(system_id,
object_name)` cannot be global without a manual overlap check;
soft-delete and `row_version` must be repeated per table; migrations
multiply.

### Option D: EAV / JSON-first (`kind` + opaque `payload: JSONB`)

One `datasets` table; a `payload` JSONB column holds all kind-specific
fields.

**Pros:** trivial schema; a new kind is a schema-less addition.
**Cons:** no DB-level types for partition counts, retention, path
formats; validation lives only in Pydantic; filters and indexes on
kind-specific fields must use JSONB expression indexes with their own
maintenance cost; SDK clients lose per-kind classes and get a
`dict[str, Any]`.

### Option E: Separate services per kind (no polymorphism)

Five independent endpoints and services: `/rdbms-datasets`,
`/kafka-datasets`, etc.

**Pros:** each endpoint is narrow and independent.
**Cons:** the concept "datasets belonging to this system" now requires
five calls; the uniqueness rule becomes a cross-table check; the SDK
and UI must stitch five resources into one catalogue view; lineage
tables (Field, FieldBinding) cannot point to "a dataset" without a
discriminator.

## 3. Trade-off Analysis

The core tension is **DB type fidelity vs. operational simplicity**.
Option B (single table) is cheap to query but forfeits type fidelity.
Option D (JSON payload) is cheap to evolve but forfeits validation.
Option C (concrete tables) gives strong isolation but makes the
catalogue view expensive and FK targets ambiguous. Option E shatters
the product concept.

Option A balances all four forces: shared columns are normalized once
(good for indexes, FKs, and soft-delete), kind-specific columns get
real types (good for constraints, filters, and SDK ergonomics), and
the discriminator makes a single `/datasets` endpoint feasible.

## 4. Recommendation

Adopt Option A. Use SQLAlchemy joined-table inheritance on the server
and a Pydantic discriminated union on the wire; keep the `kind` string
as the single source of truth shared by both.

## 5. Implementation Notes

### Canonical file set

- [`backend/models/dataset.py`](../../backend/models/dataset.py) —
  `Dataset` parent + `DatasetRdbms / DatasetKafka / DatasetStorage /
  DatasetSftp / DatasetHive` children. Parent carries
  `SoftDeleteMetaDataMixin` (ADR-006) and the common columns; children
  carry only kind-specific columns plus the PK FK.
- [`schemas/aide_schemas/dataset.py`](../../schemas/aide_schemas/dataset.py)
  — per-kind `DatasetXDetails`, `DatasetXCreate`, `DatasetXRead`,
  `DatasetXUpdate`; `AnyDatasetCreate / Read / Update` unions;
  `READ_SCHEMA_MAP` + `validate_dataset_read` helper.
- [`backend/services/dataset.py`](../../backend/services/dataset.py) —
  `DatasetService` + `MODEL_MAP`, overriding CRUD to dispatch on kind.
- [`backend/repositories/dataset.py`](../../backend/repositories/dataset.py)
  — `DatasetRepository(SoftDeleteRepository[Dataset])` with a
  `get_by_system_and_object_name` helper for the uniqueness check.
- [`backend/api/v1/datasets.py`](../../backend/api/v1/datasets.py) —
  single `/api/v1/datasets` router consuming the discriminated union.

### Parent model contract

```python
class Dataset(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "datasets"
    system_id: Mapped[uuid.UUID] = mapped_column(..., index=True)
    object_name: Mapped[str] = mapped_column(Text, nullable=False)
    layer: Mapped[str | None] = ...
    is_active: Mapped[bool] = ...
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    kind: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    __mapper_args__ = {
        "polymorphic_identity": "dataset",
        "polymorphic_on": "kind",
    }

    __table_args__ = (
        Index(
            "uq_datasets_system_id_object_name_active",
            "system_id", "object_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
```

Every child table follows a fixed shape:

```python
class DatasetKafka(Dataset):
    __tablename__ = "dataset_kafka"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), primary_key=True,
    )
    # kind-specific columns with real types
    __mapper_args__ = {"polymorphic_identity": "kafka"}
```

### Schema contract

- Each `DatasetXDetails` holds only the kind-specific fields (plus
  per-kind `extra`).
- `DatasetXCreate = DatasetCreateBase + DatasetXDetails + kind:
  Literal["x"]`.
- `DatasetXRead = DatasetReadBase + DatasetXDetails + kind:
  Literal["x"]` with `model_config = ConfigDict(from_attributes=True)`.
- `DatasetXUpdate = DatasetUpdateBase + kind: Literal["x"]` — **all**
  update fields optional; the discriminator `kind` must equal the
  current row's kind.
- Unions use `Annotated[Union[...], Field(discriminator="kind")]` so
  FastAPI / Pydantic validate the discriminator at the edge and return
  clean per-kind errors for mismatches.
- `READ_SCHEMA_MAP[kind] -> SchemaClass` and
  `validate_dataset_read(orm_obj) -> AnyDatasetRead` are the two
  helpers the service layer uses to turn a polymorphic ORM instance
  into the right Pydantic class.

### Service contract — overrides, not inheritance defaults

Unlike every other entity (ADR-002), `DatasetService` overrides every
CRUD method. Reasons:

- `create` must pick the concrete child model from `MODEL_MAP[kind]`
  and raise `INVALID_DATASET_KIND` if the discriminator is unknown.
- `get_by_id`, `get_paginated`, `delete`, `restore` must return
  `AnyDatasetRead` via `validate_dataset_read(...)`, not the generic
  `read_schema.model_validate(...)` from the base — the polymorphic
  ORM object does not round-trip through the union schema cleanly.
- `update` enforces `DATASET_KIND_MISMATCH`: the incoming
  discriminator must match the existing row's `kind`. Changing a
  Dataset's kind is not supported (it would require migrating child-
  table rows, which is out of scope).

Do **not** try to "fix" `GenericService` to handle polymorphism
generically. Polymorphism is a one-off; generalising the base to
support it would pay a complexity tax across every entity that is not
polymorphic.

### Adding a new kind

1. Create the child table model in `backend/models/dataset.py`
   (inherit from `Dataset`, FK PK to `datasets.id`, kind-specific
   columns, `polymorphic_identity="<new_kind>"`).
2. Add `DatasetNewKindDetails`, `DatasetNewKindCreate`,
   `DatasetNewKindRead`, `DatasetNewKindUpdate` in
   `schemas/aide_schemas/dataset.py`; extend the `AnyDatasetCreate /
   Read / Update` unions and `READ_SCHEMA_MAP`.
3. Add `"<new_kind>": DatasetNewKind` to `MODEL_MAP` in
   `backend/services/dataset.py`.
4. `make alembic-gen` → review → commit.
5. Update `docs/AIDE_data_model.json` to reflect the new child table.

If steps 2 and 3 get out of sync, create/update silently routes the
wrong way: the Pydantic union will reject the new discriminator (good)
or the service `MODEL_MAP.get(kind)` will return `None` (raises
`INVALID_DATASET_KIND`, also good). Both failure modes are surfaced
as user-visible errors rather than silent data corruption.

### Foreign keys onto the polymorphic set

Downstream tables (`Field`, `DatasetSchema`, `FieldBinding`) FK
**`datasets.id`**, not a per-kind id. This works because all children
share the parent's id. In the current schema these leaf-table FKs use
`ondelete="CASCADE"` (matching ADR-006's recommendation for
leaf entities); because the parent `Dataset` is only ever soft-deleted,
the cascade is never actually triggered — it is reserved for the
eventual `purge` path.

### Soft-delete and the polymorphic set

`SoftDeleteMetaDataMixin` lives only on the parent. Setting
`deleted_at` on a `Dataset` is enough to hide it from `get_multi`
and `get_multi_paginated` (ADR-002). Child rows remain in their tables
and are inaccessible through the soft-delete-aware query; they are
re-exposed on restore. Do not add `deleted_at` to child tables — it
would split the soft-delete source of truth and make restore
inconsistent.

### List responses and the N+1 shape

`get_multi_paginated` on a polymorphic model emits
`SELECT * FROM datasets` for the page and, by default, issues one
`SELECT` per child on attribute access — which Pydantic triggers when
serializing `DatasetXRead` fields. If list latency becomes a problem,
add `polymorphic_load="selectin"` on the mapper and/or an explicit
`with_polymorphic("*", [...])` in the repository query. We have not
needed this yet; revisit once a page is > 100 items or p95 latency
grows.

## 6. Consequences

- **Easier:** one catalogue endpoint; strong types for kind-specific
  fields in SDK and admin UI; uniqueness, soft-delete, and lineage FKs
  all pivot on a single `datasets` row.
- **Harder:** every CRUD method in `DatasetService` must know about
  the discriminator; the generic base (ADR-002) is not a fit; adding
  a kind is a five-file change.
- **Revisit when:** the number of kinds grows past ~10 (a code-
  generation step from a single YAML spec may become worthwhile), or
  when list-view latency pushes us to tune joined loading explicitly.
