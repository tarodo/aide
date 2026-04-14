# RDBMS Metadata Crawler — Design Spec

## Overview

Crawler system for collecting metadata from RDBMS databases and populating the AIDE metastore. Built as three separate packages in the monorepo: shared schemas, SDK, and crawler.

## Decisions

| Decision | Choice |
|----------|--------|
| RDBMS vendors | Vendor-agnostic via SQLAlchemy Inspector |
| Integration | SDK wrapping REST API |
| Code location | Monorepo: `schemas/`, `sdk/`, `crawler/` alongside `backend/` |
| Job management | CLI trigger + crawl history table in metastore |
| Introspection method | SQLAlchemy Inspector only (no custom SQL scripts) |
| Re-crawl strategy | Detect diff and report; human decides what to apply |
| Metadata depth | Maximum: tables, columns, types, PKs, FKs, indexes, views, comments, unique constraints |

## Architecture

```
aide/
├── schemas/              # Package: aide-schemas (Pydantic models only)
│   ├── pyproject.toml
│   └── aide_schemas/
│       ├── system_kinds.py
│       ├── system_flavors.py
│       ├── data_types.py
│       ├── systems.py
│       ├── credential_refs.py
│       ├── datasets.py
│       ├── fields.py
│       ├── dataset_schemas.py
│       ├── field_bindings.py
│       ├── type_instances.py
│       ├── cast_rules.py
│       ├── crawl_runs.py
│       └── ...
├── backend/              # Existing metastore, depends on aide-schemas
├── sdk/                  # Package: aide-sdk, depends on aide-schemas
│   ├── pyproject.toml
│   └── aide_sdk/
│       ├── client.py
│       ├── auth.py
│       ├── resources/
│       │   ├── systems.py
│       │   ├── datasets.py
│       │   ├── fields.py
│       │   ├── dataset_schemas.py
│       │   ├── field_bindings.py
│       │   ├── type_instances.py
│       │   ├── data_types.py
│       │   ├── system_flavors.py
│       │   ├── crawl_runs.py
│       │   └── ...
│       ├── models.py       # Re-exports from aide-schemas
│       └── exceptions.py
├── crawler/              # Package: aide-crawler, depends on aide-sdk
│   ├── pyproject.toml
│   └── aide_crawler/
│       ├── __main__.py
│       ├── cli.py
│       ├── inspector.py
│       ├── normalizer.py
│       ├── differ.py
│       ├── reporter.py
│       ├── runner.py
│       └── type_map.py
└── docs/
```

## Shared Schemas Package

Pydantic models extracted from `backend/schemas/` into standalone `schemas/` package. Both `backend` and `sdk` depend on `aide-schemas`. No SQLAlchemy or other backend-specific dependencies.

Contains all Create/Read/Update DTOs and shared mixins (UUIDMixin, TimestampMixin, NoteMixin, VersionedUpdateMixin, MetaDataMixin, etc.).

## SDK Design

### Client

```python
async with AideClient(base_url="http://localhost:8001", username="crawler@aide", password="...") as client:
    systems = await client.systems.list(filters={"flavor_id": "..."})
    dataset = await client.datasets.create(DatasetRdbmsCreate(...))
    page = await client.datasets.list(page=1, size=50, filters={"system_id": "..."})
```

- Async HTTP client via `httpx.AsyncClient`
- JWT auth with transparent token refresh on 401
- Optional sync wrapper via `aide_sdk.sync` for simpler scripting

### Resource pattern

Each entity exposed as a resource class:

```python
class DatasetsResource:
    def __init__(self, client: HttpClient): ...
    async def list(self, page, size, filters, sort) -> PaginatedResponse[DatasetRead]: ...
    async def get(self, obj_id: UUID) -> DatasetRead: ...
    async def create(self, data: AnyDatasetCreate) -> DatasetRead: ...
    async def update(self, obj_id: UUID, data: AnyDatasetUpdate) -> DatasetRead: ...
    async def delete(self, obj_id: UUID) -> None: ...
```

### Error handling

Typed exceptions wrapping HTTP status codes: `NotFoundError`, `ConflictError`, `ValidationError`, `AuthError`. Crawler uses these for diff logic (e.g., 404 = entity not in metastore).

## Crawler Pipeline

```
CLI command
    │
    ▼
┌─────────┐    ┌────────────┐    ┌────────────┐    ┌──────────┐    ┌──────────┐
│ Inspector│───▶│ Normalizer │───▶│   Differ   │───▶│ Reporter │───▶│  Logger  │
│          │    │            │    │            │    │          │    │          │
│ SQLAlchemy    │ Inspector  │    │ Normalized │    │ Diff     │    │ CrawlRun │
│ inspect()│    │ output →   │    │ vs current │    │ → stdout │    │ → API    │
│ on target│    │ SDK models │    │ metastore  │    │ / JSON   │    │          │
└─────────┘    └────────────┘    └────────────┘    └──────────┘    └──────────┘
```

### Inspector (`inspector.py`)

Connects to target RDBMS via SQLAlchemy `create_engine` + `inspect()`. Collects per schema:

- `get_schema_names()` — schema list
- `get_table_names(schema)` + `get_view_names(schema)` — tables and views
- `get_columns(table, schema)` — columns with types
- `get_pk_constraint(table, schema)` — primary keys
- `get_unique_constraints(table, schema)` — unique constraints
- `get_foreign_keys(table, schema)` — foreign key relationships
- `get_indexes(table, schema)` — indexes
- `get_table_comment(table, schema)` — table/column comments

Output: raw dict structure, not yet mapped to SDK models.

Filtering via CLI flags: `--schemas`, `--tables`, `--exclude-schemas`, `--exclude-tables`. Default: all user schemas (excluding system schemas like `information_schema`, `pg_catalog`, etc.).

Uses sync engine with `run_sync()` pattern since SQLAlchemy `inspect()` does not support async.

### Normalizer (`normalizer.py`)

Maps Inspector output to SDK Pydantic models:

- Each table/view → `DatasetRdbmsCreate` with `catalog_name`, `schema_name`, `table_name`, `is_view`, `pk_columns`, `uq_constraints`
  - `object_name` composed as `{schema_name}.{table_name}` (unique per system). For MySQL (no schema concept): `{database}.{table_name}`
- Each column → `FieldCreate` with `name`, `path` (path = column name for flat RDBMS columns)
- SQL type → `TypeInstanceCreate` via type_map

### Type mapping (`type_map.py`)

Maps `(dialect_name, sql_type_class)` → `DataType.code` for the given SystemFlavor.

- Extracts parameters (length, precision, scale) into `TypeInstance.type_params`
- Expects DataTypes pre-populated as seed data for each SystemFlavor
- Fallback to generic type if exact mapping not found
- Unknown types logged as warning; field created without TypeInstance

### Differ (`differ.py`)

Compares normalized crawled state vs current metastore state (fetched via SDK):

```python
@dataclass
class TypeChange:
    dataset_id: UUID
    field_name: str
    old_type: str          # DataType.code in metastore
    new_type: str          # DataType.code from crawl
    old_params: dict       # TypeInstance.type_params in metastore
    new_params: dict       # TypeInstance.type_params from crawl

@dataclass
class IndexChange:
    dataset_id: UUID
    index_name: str
    columns: list[str]
    is_unique: bool

@dataclass
class DiffResult:
    new_datasets: list[DatasetRdbmsCreate]
    removed_datasets: list[DatasetRead]
    new_fields: dict[UUID, list[FieldCreate]]
    removed_fields: dict[UUID, list[FieldRead]]
    type_changes: list[TypeChange]
    new_indexes: dict[UUID, list[IndexChange]]
    removed_indexes: dict[UUID, list[IndexChange]]
```

### Reporter (`reporter.py`)

Formats `DiffResult`:
- `--format text` — human-readable stdout (default)
- `--format json` — machine-readable JSON
- `-o <file>` — write to file

### Logger

Records `CrawlRun` via SDK after completion.

## CrawlRun Entity (new in backend)

### Model

```python
class CrawlStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class CrawlRun(MetaDataMixin, Base):
    __tablename__ = "crawl_runs"

    system_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("systems.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- Uses `MetaDataMixin` (hard delete) — audit log, not business entity
- `config` stores CLI params (schemas, filters, connection details without passwords)
- `summary` stores diff counts: `{"new_datasets": 5, "removed_datasets": 1, "new_fields": 23, "type_changes": 2}`
- Full diff report NOT stored in CrawlRun — CLI output only (`--format json -o report.json`)
- No `row_version` — only status transitions (running → completed/failed)

### API endpoints

```
POST   /api/v1/crawl-runs       # Create (crawler reports start)
PATCH  /api/v1/crawl-runs/{id}  # Update status/summary (crawler reports completion)
GET    /api/v1/crawl-runs       # List with filters (by system_id, status, date range)
GET    /api/v1/crawl-runs/{id}  # Get single run
```

No DELETE — audit log is immutable.

## CLI Interface

```bash
# Full crawl pipeline
aide-crawler crawl --system-code postgres-prod

# With filters
aide-crawler crawl --system-code postgres-prod \
    --schemas public,analytics \
    --exclude-tables _migrations,_alembic

# Output diff as JSON to file
aide-crawler crawl --system-code postgres-prod --format json -o report.json

# Inspect only — no metastore interaction, no CrawlRun
aide-crawler inspect --connection-url "postgresql+psycopg2://..." --schemas public
```

Two commands:
- `crawl` — full pipeline: inspect → normalize → diff → report → log. Requires `--system-code` (system registered in metastore).
- `inspect` — introspection only, raw metadata output. For debugging and exploration. No metastore interaction.

## Connection Management

### Target RDBMS connection (MVP)

Crawler does NOT resolve `CredentialRef` automatically. Connection string passed explicitly:

```bash
# CLI flag
aide-crawler crawl --system-code postgres-prod \
    --connection-url "postgresql+psycopg2://user:pass@host:5432/db"

# Environment variable
export AIDE_CRAWLER_CONNECTION_URL="postgresql+psycopg2://..."
aide-crawler crawl --system-code postgres-prod
```

Future: pluggable credential resolvers (Vault, AWS Secrets Manager) by `CredentialRef.provider`.

### Metastore connection

Crawler authenticates to metastore as technical user (`user_type=technical`). SDK handles JWT login/refresh.

### Config file (optional)

```yaml
# aide-crawler.yaml
metastore:
  base_url: http://localhost:8001
  username: crawler@aide
  password: ${AIDE_METASTORE_PASSWORD}

defaults:
  exclude_schemas:
    - information_schema
    - pg_catalog
    - pg_toast
```

Priority: CLI flags > config file > environment variables.

## Complexities & Risks

### 1. DataType seed data

Crawler expects `DataType` records pre-populated for each `SystemFlavor` (e.g., PostgreSQL flavor must have `varchar`, `integer`, `numeric`, `jsonb`, etc.).

If DataType not found, crawler cannot create TypeInstance. Crawler validates at startup that SystemFlavor has base DataTypes — fail fast with clear message if missing. Seed data delivered separately (migration or script).

### 2. Type mapping ambiguity

SQLAlchemy Inspector returns both generic types (`VARCHAR`) and dialect-specific (`JSONB`, `SERIAL`). Same SQL type may map differently per dialect.

`type_map.py` maps by `(dialect_name, sql_type_class) → DataType.code`. Fallback to generic type. Unknown types logged as warning, field created without TypeInstance.

### 3. Large schemas

Databases with thousands of tables, tens of thousands of columns. Many Inspector queries, many SDK HTTP calls.

Mitigations:
- Inspector: batch introspection per schema
- SDK: paginated list calls for current metastore state
- CLI filters (`--schemas`, `--tables`) to limit scope

### 4. Schema name mapping

`DatasetRdbms` has `catalog_name` + `schema_name` + `table_name`. Not all RDBMS use catalog concept the same way. PostgreSQL: database = catalog, schema = schema. MySQL: database = schema, no catalog.

Normalizer accounts for dialect. Convention: `catalog_name` = database name (or null), `schema_name` = schema/database per vendor semantics.

### 5. Async Inspector limitation

SQLAlchemy `inspect()` only works with sync engine. Async engine not supported.

Use `run_sync()` on async connection or create separate sync engine for introspection. Documented SQLAlchemy pattern.

### 6. Network topology

Crawler needs network access to both target RDBMS and metastore API. May be different networks in production.

Not solved in MVP. Crawler runs where both are reachable. Future: agent-based architecture.

## Out of Scope (MVP)

- Automatic CredentialRef resolution
- Auto-apply of diff (human decides)
- Scheduling / cron for crawl runs
- Non-RDBMS crawlers (Kafka, S3, Hive)
- Bulk SDK operations
- DDL change detection for column modifications (manual process)
- Nested type decomposition (JSONB, composite types)
