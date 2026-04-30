# Engines — Pipeline-Driver Entity Attached to DatasetLink

**Date:** 2026-04-30
**Status:** Draft (awaiting review)
**Scope:** Introduce a new top-level entity `Engine` that represents the tool driving a single pipeline hop (CDC engine on a source→Kafka link; compute engine on a Kafka→Lake or Lake→Lake link). Engine is polymorphic across four concrete kinds (Debezium, OGG, Spark, Impala). The metastore stores engine metadata (envelope template for CDC, dialect/runtime opts for compute) and exposes a sync render endpoint that returns SQL text for a given link. No DDL, no execution, no auto-provisioning of Kafka schemas in this phase.

**Related ADRs:** ADR-008 (polymorphic Dataset — same pattern reused for Engine), ADR-010 (enum-as-varchar), ADR-016 (two-level lineage — DatasetLink), ADR-018 (schema-pinned lineage), ADR-019 (lake-sync — explicitly deferred engine concerns to this phase). New: ADR-020 will be authored alongside this spec to record the engine-as-driver decision and its alternatives.

---

## 1. Context and Problem

ADR-019 deferred engine-specific concerns: "Engines (Impala, Spark) read these tables but are irrelevant to the metastore — engine-specific concerns (DDL dialect, runtime config) belong in a later phase." This spec opens that phase.

Two operator pains today:

1. **Compute side.** Once a `DatasetLink` is pinned, an engineer hand-writes the Spark/Impala SQL that reads the source side and writes the target side. The metastore knows source/target field types and the cast plan, but cannot emit a SELECT/INSERT skeleton — even though every input it needs is already there.

2. **CDC side.** When a source RDBMS is mirrored to Kafka via Debezium or OGG, the kafka topic carries an envelope (Debezium: `before/after/source/op/ts_ms`; OGG: a different shape). A downstream Spark consumer must know which envelope it is reading to extract the actual columns (`get_json_object(payload, '$.after.foo')` for Debezium-JSON, `payload.after.foo` for Avro). That knowledge lives in the operator's head and in scattered config — not in the metastore.

Both pains are pipeline-hop properties: which tool drives the hop, and how does that tool shape the bytes flowing through it. The natural attachment point is `DatasetLink` (which already represents one hop). A new `Engine` entity, attached to a link, is the missing piece.

## 2. Goals / Non-Goals

**Goals:**

- New polymorphic `Engine` entity with four concrete kinds:
  - `engine_debezium` (CDC role)
  - `engine_ogg` (CDC role)
  - `engine_spark` (compute role)
  - `engine_impala` (compute role)
- Each engine instance carries metadata about its transformation:
  - **CDC engines:** an `envelope_template` (JSONB) describing where source columns sit inside the Kafka payload (`before`, `after`, `op`, `ts_ms` paths).
  - **Compute engines:** `runtime_opts` (JSONB) for dialect-specific options (output mode, runtime hints).
- Standard CRUD: `POST/GET/LIST/PATCH/DELETE /api/v1/engines/`. Polymorphic create per the project pattern (see `Dataset`).
- Attach point: a new nullable FK `engine_id` on `DatasetLink`. One engine per active link. Attach/detach via `PATCH /api/v1/dataset_links/{id}`. RESTRICT delete on engine while a link still references it.
- New action endpoint: `POST /api/v1/dataset_links/{id}/render-sql` — returns a SQL string in the engine's dialect for the given link. Stateless, no persistence, no execution.
- New service `EnvelopeResolver` — read-only helper used by the SQL renderer to compute "source field → kafka payload path" given the CDC engine attached to the upstream link in the lineage chain.
- Hardcoded engine↔link compatibility matrix: CDC engines only on RDBMS→Kafka links; compute engines only on links targeting a lake dataset (Kafka→Hive, Hive→Hive). Violations raise `409 ENGINE_INCOMPATIBLE_LINK`.
- Lockstep bump of `aide-schemas` and `aide-sdk`. SDK gets `EnginesResource` plus `dataset_links.render_sql(link_id)`.

**Non-Goals (deferred):**

- **Auto-provisioning of Kafka chains from a CDC engine.** A future phase will add `POST /api/v1/dataset_links/{id}/cdc-sync` that, given a source RDBMS and an attached Debezium/OGG engine, creates the target `DatasetKafka` + Field/TypeInstance chain wrapped in the engine's envelope. Out of scope here. The engine config stored in this phase is exactly the input that endpoint will consume.
- **DDL rendering.** Render returns SELECT/INSERT pipeline SQL only. `CREATE TABLE` for the target lake stays manual / external. A later phase will return `{ddl, sql}` together (engine × layer matrix is a separate problem).
- **Execution.** No "run this SQL" capability. Render is metastore output; running it is the orchestrator's job (Airflow / dbt / etc.).
- **Persisted render history.** Render is stateless. No `RenderedQuery` table. If history is needed later, it can be layered on top.
- **Credential / connection info on Engine.** Engine is pure transformation metadata. Connection details belong to the executor. A future phase can add an optional `credential_ref_id` once an execution layer exists.
- **Engine flavor catalog.** No `engine_flavors` table. Version is a string field validated by Pydantic whitelist per subtype.
- **Many engines per link.** FK is one-to-one. If a real use case for multiple engines per hop emerges, schema can migrate to a junction table later.
- **Engine-driven schema evolution.** Engines do not edit `DatasetSchema` / `FieldBinding`. They only describe how an existing schema is transported.
- **Inverse-CDC** (Lake→Kafka via compute engines). Compute engines on lake-targeted links only in this phase.

---

## 3. Data Model

One new base table + four subtype tables, following the polymorphic pattern of `Dataset` (ADR-008). One nullable FK on `DatasetLink`. No changes to other tables.

### 3.1 Base table `engines`

```python
class Engine(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "engines"

    code: Mapped[str] = mapped_column(String(255), nullable=False)         # human id, e.g. "debezium-prod-cluster-1"
    name: Mapped[str] = mapped_column(Text, nullable=False)                # display name
    kind: Mapped[str] = mapped_column(String(64), nullable=False)          # discriminator: debezium|ogg|spark|impala
    role: Mapped[str] = mapped_column(String(16), nullable=False)          # cdc|compute (denormalized for filter convenience)
    version: Mapped[str] = mapped_column(String(64), nullable=False)       # whitelisted per subtype via Pydantic

    __mapper_args__ = {"polymorphic_identity": "engine", "polymorphic_on": "kind"}

    __table_args__ = (
        Index(
            "uq_engines_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("role IN ('cdc', 'compute')", name="ck_engines_role"),
    )
```

`role` is denormalized from `kind` (debezium/ogg → cdc; spark/impala → compute). Stored explicitly so list-filter `role=cdc` is a single index hit, and so service-layer compatibility checks read it without re-mapping `kind`.

### 3.2 Subtype tables

```python
class EngineDebezium(Engine):
    __tablename__ = "engine_debezium"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("engines.id"), primary_key=True)
    envelope_template: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    topic_routing: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    __mapper_args__ = {"polymorphic_identity": "debezium"}


class EngineOgg(Engine):
    __tablename__ = "engine_ogg"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("engines.id"), primary_key=True)
    envelope_template: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    topic_routing: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    __mapper_args__ = {"polymorphic_identity": "ogg"}


class EngineSpark(Engine):
    __tablename__ = "engine_spark"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("engines.id"), primary_key=True)
    runtime_opts: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    __mapper_args__ = {"polymorphic_identity": "spark"}


class EngineImpala(Engine):
    __tablename__ = "engine_impala"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("engines.id"), primary_key=True)
    runtime_opts: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    __mapper_args__ = {"polymorphic_identity": "impala"}
```

CDC subtypes share `envelope_template` + `topic_routing`. Compute subtypes share `runtime_opts`. Per project precedent (Dataset polymorphic, single-level), we keep the inheritance flat — duplicated columns across CDC subtypes are intentional and trivial (the alternative, two-level joined inheritance, is not used elsewhere in this codebase).

### 3.3 `envelope_template` shape (CDC engines)

JSONB document with engine-defined paths. Default templates seeded as constants in code (no YAML for this phase — the templates are tight and engine-canonical):

```jsonc
// Debezium 2.x default
{
  "envelope_kind": "debezium",
  "after_path": "after",
  "before_path": "before",
  "op_path": "op",
  "ts_ms_path": "ts_ms",
  "source_path": "source"
}

// OGG 21c default
{
  "envelope_kind": "ogg",
  "after_path": "after",
  "before_path": "before",
  "op_path": "op_type",
  "ts_path": "op_ts",
  "table_path": "table"
}
```

Operators may override the dict at create time. `EnvelopeResolver` only reads `*_path` keys, so unknown keys are tolerated and round-trip safely.

### 3.4 `DatasetLink.engine_id`

```python
engine_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True),
    ForeignKey("engines.id", ondelete="RESTRICT"),
    nullable=True,
    index=True,
)
engine = relationship("Engine")
```

Nullable: existing links migrate without a value. RESTRICT applies on hard delete only; engines are soft-deleted via `SoftDeleteMetaDataMixin`, so the real "engine in use" gate is the service-level `ENGINE_IN_USE` check before flipping `deleted_at`. RESTRICT is defense-in-depth for accidental SQL-level deletes. The link's existing `(source_dataset_id, target_dataset_id)` unique-active index is unchanged.

### 3.5 Migration

One Alembic migration:

1. Create `engines` (base) + four subtype tables with their FKs to `engines.id`.
2. Add nullable `engine_id` column + index + FK on `dataset_links`.
3. No backfill; existing links stay engine-less.

Downgrade drops the column and tables. Safe because no rows exist before this migration.

---

## 4. Behavior

### 4.1 CRUD on engines

Standard polymorphic CRUD, modeled after `Dataset`:

- `POST /api/v1/engines/` accepts a discriminated union by `kind`. Pydantic dispatches to `EngineDebezimCreate | EngineOggCreate | EngineSparkCreate | EngineImpalaCreate`. Each subtype enforces its `version` whitelist (`Literal["2.x", "1.x"]` for Debezium, `Literal["21c", "19c"]` for OGG, `Literal["3.x", "4.x"]` for Spark, `Literal["4.x"]` for Impala — refine during implementation against actual operator needs).
- `GET /api/v1/engines/{id}` returns the polymorphic shape (subtype fields included).
- `LIST /api/v1/engines/` supports filter by `role` and `kind`, sort by `code`/`created_at`. Uses `get_filter_sort_dependency` (CLAUDE.md note: filter_model required, sortable as `set[str]`).
- `PATCH /api/v1/engines/{id}` updates non-discriminator fields. `kind` is immutable (changing kind changes subtype table — not supported).
- `DELETE /api/v1/engines/{id}` — soft delete via `SoftDeleteMetaDataMixin`. Returns `409 ENGINE_IN_USE` if any active `DatasetLink` references it (RESTRICT FK protects DB-level too).

### 4.2 Attach / detach engine on a link

`PATCH /api/v1/dataset_links/{id}` gains an optional `engine_id` field. Three behaviors:

- `engine_id: <uuid>` — attach. Service validates compatibility (§4.3); returns `409 ENGINE_INCOMPATIBLE_LINK` on mismatch. Returns `404 ENGINE_NOT_FOUND` if engine missing or soft-deleted.
- `engine_id: null` — explicit detach.
- field omitted — no change.

Service is `DatasetLinkService.update`; logic added in the same UoW that already validates schema pin coherence. Engine attach/detach is atomic with the rest of the patch.

### 4.3 Compatibility matrix (hardcoded)

In `backend/services/engine_compatibility.py`:

```python
# (engine.role, source_dataset.kind, target_dataset.kind) -> bool
_ALLOWED: set[tuple[str, str, str]] = {
    ("cdc", "rdbms", "kafka"),
    ("compute", "kafka", "hive"),
    ("compute", "hive", "hive"),
}
```

Service raises `AppException("ENGINE_INCOMPATIBLE_LINK", details={"engine_role": ..., "source_kind": ..., "target_kind": ...})` on miss. New entries are added to this set as the project supports new pipeline shapes; the YAML-codified version of this matrix (mirroring `cast_rules` seed pattern) is deferred — too few combinations today to justify the seed pipeline.

### 4.4 Render SQL endpoint

`POST /api/v1/dataset_links/{id}/render-sql` — stateless action. Behavior:

1. Load the link with engine, source schema, target schema, all field bindings, all type instances eager-loaded (`selectinload` chain).
2. Reject with `409 ENGINE_NOT_ATTACHED` if `engine_id` is null. Reject with `409 ENGINE_NOT_RENDERABLE` if engine role is `cdc` (CDC engines describe envelopes, they do not produce SELECT/INSERT — that belongs to the future cdc-sync endpoint).
3. Walk lineage upstream to find a CDC engine on a parent link, if any. Mechanism: query for an active `DatasetLink` whose `target_dataset_id` equals the current link's `source_dataset_id`. If found and that link has a CDC engine attached, pass it (plus the source `DatasetKafka.format`) into `EnvelopeResolver`. At most one parent link is walked — multi-hop CDC chains are out of scope. If no parent link or no CDC engine on parent, resolver is constructed in pass-through mode.
4. Dispatch to `SparkRenderer` or `ImpalaRenderer` based on engine `kind`. Renderer emits a single `INSERT INTO <target> SELECT <projections> FROM <source>` string. Projection list is built one entry per `FieldLink` in the link.
5. Return `{"sql": "<string>", "engine_id": ..., "engine_kind": ..., "warnings": [...]}`.

Renderers live in `backend/services/engine_render/`:

- `base.py` — `EngineRenderer` Protocol with `render(link, envelope_resolver) -> RenderResult`.
- `spark.py` — `SparkRenderer`.
- `impala.py` — `ImpalaRenderer`.

The renderer uses each `FieldLink` to emit a projection. For each target field, the source column expression is computed by:

- If source dataset is `kafka` and the upstream link has a CDC engine: `EnvelopeResolver.path_for(source_field)` returns e.g. `get_json_object(payload, '$.after.<col>')` or `payload.after.<col>` depending on the kafka dataset's `format`.
- Otherwise: the source column name as-is.

Cast operations (from the link's pinned schemas + `CastRule.target_dt`) become `CAST(... AS <target_type>)` calls; expressions are dialect-quoted by the renderer. Renderer warnings (e.g. `LOSSY_CAST applied`) bubble up in the response.

### 4.5 EnvelopeResolver service

`backend/services/envelope_resolver.py`. Signature:

```python
class EnvelopeResolver:
    def __init__(self, cdc_engine: Engine | None, kafka_format: str): ...
    def path_for(self, source_field_name: str, side: Literal["after", "before"] = "after") -> str: ...
    def op_path(self) -> str: ...
    def ts_path(self) -> str: ...
```

If `cdc_engine` is None, `path_for(name)` returns the bare column name (no envelope). Otherwise, it composes `<after_path>.<name>` (or the dialect-appropriate JSON extractor based on `kafka_format`). Pure read-only; no DB access at call time — engine + kafka dataset are pre-loaded by the caller.

### 4.6 Soft-delete semantics

Engine uses `SoftDeleteMetaDataMixin` like Dataset/System. Per CLAUDE.md "soft-delete coverage by mixin" rule, all engine lookups must check `deleted_at IS NULL`. RESTRICT FK on `dataset_links.engine_id` ensures DB-level integrity even if a service-level check is missed.

### 4.7 Error codes

| Code | Status | When |
|------|--------|------|
| `ENGINE_NOT_FOUND` | 404 | Engine id absent or soft-deleted |
| `ENGINE_IN_USE` | 409 | Delete attempted while a `DatasetLink` references it |
| `ENGINE_INCOMPATIBLE_LINK` | 409 | Attach where (role, source.kind, target.kind) not in matrix; details include all three |
| `ENGINE_NOT_ATTACHED` | 409 | Render called on a link with no engine |
| `ENGINE_NOT_RENDERABLE` | 409 | Render called with a CDC engine attached |
| `ENGINE_KIND_IMMUTABLE` | 409 | PATCH attempted to change `kind` |
| `ENGINE_VERSION_INVALID` | 422 | `version` outside the per-subtype whitelist |

`details` payloads follow the `LAKE_SYNC_AMBIGUOUS_CAST` precedent in CLAUDE.md (top-level `details` key in response body).

---

## 5. API Surface

### 5.1 Engine CRUD

```
POST   /api/v1/engines/
GET    /api/v1/engines/?role=cdc&kind=debezium&limit=50&sort=-created_at
GET    /api/v1/engines/{id}
PATCH  /api/v1/engines/{id}
DELETE /api/v1/engines/{id}
```

Polymorphic create body:

```jsonc
{
  "kind": "debezium",
  "code": "debezium-prod-cluster-1",
  "name": "Production Debezium",
  "version": "2.x",
  "envelope_template": { "envelope_kind": "debezium", "after_path": "after", ... },
  "topic_routing": null
}
```

### 5.2 Attach/detach

`PATCH /api/v1/dataset_links/{id}` body gains optional `engine_id: UUID | null`. No new endpoint.

### 5.3 Render

```
POST /api/v1/dataset_links/{id}/render-sql
```

Empty body. Response:

```jsonc
{
  "engine_id": "...",
  "engine_kind": "spark",
  "sql": "INSERT INTO ... SELECT ...",
  "warnings": [{ "code": "LOSSY_CAST", "field": "amount", "from": "numeric(38,10)", "to": "decimal(38,9)" }]
}
```

### 5.4 SDK additions

- `client.engines` resource with full CRUD plus polymorphic factory helpers (`create_debezium`, `create_spark`, ...).
- `client.dataset_links.render_sql(link_id) -> RenderResult`.

`aide-schemas` adds `EngineBase`, `EngineDebeziumCreate/Read`, `EngineOggCreate/Read`, `EngineSparkCreate/Read`, `EngineImpalaCreate/Read`, `EngineUpdate`, `EngineFilter`, `RenderResult`. `aide-sdk` re-exports.

---

## 6. Validation Rules

### 6.1 Pydantic schemas

- `EngineCreate` is a discriminated union (`Field(discriminator="kind")`) over the four subtype schemas.
- Per-subtype `version` field uses `Literal[...]` whitelist. Concrete starting set (revisit during implementation if operator needs differ): Debezium `{"2.x", "1.x"}`, OGG `{"21c", "19c"}`, Spark `{"3.x", "4.x"}`, Impala `{"4.x"}`.
- `envelope_template` is a structural JSON object (`dict[str, Any]`) at the schema level; semantic validation (presence of `after_path`/`op_path`) happens in the Pydantic model via a `model_validator` on the CDC subtypes.
- `runtime_opts` is left fully open (`dict[str, Any] | None`); engine-specific keys vary too widely to whitelist now.

### 6.2 Service-level checks

- `EngineService.create` enforces `code` uniqueness among active rows (UoW lookup) before insert (defense in depth alongside the partial unique index).
- `DatasetLinkService.update` runs `EngineCompatibility.assert_allowed(engine, link)` before saving when `engine_id` is provided.
- `DatasetLinkService.render_sql` rejects CDC-engine links and missing-engine links with the specific error codes above.

---

## 7. Testing Strategy

Mirror existing layered tests (CLAUDE.md "Testing"):

- `tests/models/test_engine.py` — polymorphic mapper, discriminator round-trip, soft-delete query exclusion.
- `tests/repositories/test_engine_repository.py` — CRUD on each subtype, list filter by `role`/`kind`.
- `tests/services/test_engine_service.py` — create dispatch, version whitelist, code uniqueness, in-use protection on delete (mocked UoW per `_MockUnitOfWork` pattern).
- `tests/services/test_engine_compatibility.py` — matrix coverage, error code shape.
- `tests/services/test_envelope_resolver.py` — debezium/ogg path composition; null-engine pass-through.
- `tests/services/test_engine_render.py` — Spark and Impala renderer happy paths, lossy-cast warning surface, golden-file SQL fixtures (one per renderer × representative link shape).
- `tests/api/test_engines.py` — full CRUD via authenticated `httpx.AsyncClient` (per CLAUDE.md auth pattern).
- `tests/api/test_dataset_link_engine.py` — attach via PATCH (success + incompatible matrix), detach, render endpoint (success + four 409 paths).

Render tests use small, hand-written `DatasetLink` fixtures (≤ 3 fields) and golden SQL strings for stability. Renderer changes that affect golden output require explicit fixture updates.

---

## 8. Documentation

- New ADR `docs/adr/adr-020-engines-as-pipeline-driver.md`, written alongside this spec, recording: polymorphic Engine over flat-with-JSONB; FK on `DatasetLink` (one-to-one) over junction table; metadata-only Engine (no creds); deferred auto-provisioning and DDL.
- Update `docs/AIDE_data_model.json` (ChartDB) with `engines` + four subtypes and the `dataset_links.engine_id` relationship (CLAUDE.md "Data model documentation").
- Update `docs/adr/README.md` index.

---

## 9. Open Questions

None blocking implementation. Items listed under §2 Non-Goals are deliberate deferrals, not open questions.

## 10. Future Phases (Out of Scope Here)

- **CDC-sync endpoint** — `POST /api/v1/dataset_links/{id}/cdc-sync` mirroring lake-sync. Consumes the `envelope_template` stored here to auto-create the target Kafka chain.
- **DDL render** — extend `/render-sql` response to `{ddl, sql}`. Engine × layer dialect matrix.
- **Persisted renders** — `RenderedQuery` history table.
- **Execution layer** — credential refs on Engine; orchestrator integration.
- **Engine flavor catalog** — promote `version` whitelists to a seeded `engine_flavors` catalog if envelope/dialect quirks proliferate per version.
