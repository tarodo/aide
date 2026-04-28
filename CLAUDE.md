# AIDE Metastore

## Commands

| Command | Purpose |
|---------|---------|
| `make up` | Start app + DB via Docker Compose |
| `make stop` | Stop Docker Compose services |
| `make run` | Run uvicorn locally (port 8001) |
| `make check` | Lint + type-check (ruff, black --check, mypy) |
| `make format` | Auto-format (black + ruff --fix) |
| `make test-docker` | Run tests in Docker (pytest + coverage) |
| `make alembic-gen` | Auto-generate migration from model changes |
| `make alembic-head` | Apply migrations to head |
| `uv run python -m backend.scripts.seed_data_types --file backend/scripts/data/postgres14.yaml` | Seed PG14 data types |

Package manager: `uv`. Python ≥ 3.13.

## Architecture

Monorepo with 4 packages wired via `[tool.uv.sources]` in root pyproject.toml:
- `backend/` — FastAPI metastore (depends on aide-schemas)
- `schemas/` — shared Pydantic DTOs (`aide-schemas`, zero backend deps)
- `sdk/` — async REST client (`aide-sdk`, depends on aide-schemas)
- `crawler/` — RDBMS metadata crawler CLI (`aide-crawler`, depends on aide-sdk)

Layered async FastAPI app in `backend/`:

```
backend/
├── api/v1/          # FastAPI routers (REST endpoints)
├── services/        # Business logic (GenericService base)
├── repositories/    # DB access (BaseRepository generic CRUD)
├── models/          # SQLAlchemy 2.0 async ORM
├── schemas/         # Re-exports from aide-schemas (backward compat)
├── core/            # Config, auth, errors
├── db/              # Session, UoW pattern
└── alembic/         # Migrations
```

Request flow: Router → Service → UoW → Repository → Model.

New entities follow this pattern: add model, repository, service, schemas (in `schemas/aide_schemas/` + re-export in `backend/schemas/`), router, then wire in `main.py`.

## Environment

Copy `.env.example` → `.env` and `db.env.example` → `db.env` before first run. Key vars: `DATABASE_URL`, `JWT_SECRET_KEY`.

## Conventions

### Enum fields

Enum-like fields are stored as `varchar` in PostgreSQL. Validation happens at the application level via Python `str, enum.Enum` and Pydantic schemas. Do **not** use PostgreSQL native `CREATE TYPE ... AS ENUM`.

**Pattern:**
```python
# models/example.py
class MyStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

status: Mapped[str] = mapped_column(String(20), nullable=False)

# schemas/example.py — use the same enum for Pydantic validation
status: MyStatus
```

**Rationale:** Native PG enums require painful migrations (`ALTER TYPE` cannot run inside a transaction, values cannot be removed). String columns with app-level validation are simpler to evolve.

### Timestamp columns (soft-delete mixin)

`deleted_at` and other `SoftDeleteMetaDataMixin` timestamps are `TIMESTAMP WITHOUT TIME ZONE`. When setting them manually (e.g. in tests to trigger soft-delete branches), use naive datetimes: `datetime.now(timezone.utc).replace(tzinfo=None)`. Aware datetimes are rejected by asyncpg.

### Soft-delete coverage by mixin

Soft-delete varies per model. `SoftDeleteMetaDataMixin` adds `deleted_at` (e.g. `System`, `SystemFlavor`, `Dataset`, `DataType`); `MetaDataMixin` does not (e.g. `TechFieldTemplate`, `Field`, `FieldBinding`). When resolving an entity by id and rejecting "not found", check the mixin: soft-delete-capable models need `if X is None or X.deleted_at is not None`.

### Schema re-exports

Files in `backend/schemas/` are re-export shims of `aide_schemas`. Use the alias form `from aide_schemas.X import Y as Y` (no `__all__`, no docstring). mypy/ruff treat the alias form as explicit re-export. Sample: `backend/schemas/cast_rule.py`.

### Error responses

`AppException(error_code, details: dict | None = None)` — pass `details` for structured per-error payloads. The exception handler surfaces `details` under a top-level key in the response body alongside `error_code` / `detail`. Example: `LAKE_SYNC_AMBIGUOUS_CAST` carries `{field, candidates}`.

### Package layout

Root `pyproject.toml` is the backend package (no separate `backend/pyproject.toml`). Add backend deps to the root file.

### Data model documentation

When adding or modifying SQLAlchemy models, update `docs/AIDE_data_model.json` (ChartDB format) to keep the ER diagram in sync. Add/update tables, fields, and relationships matching the model changes.

### Architecture Decision Records (ADRs)

Architectural decisions live in `docs/adr/`. Filename convention: `adr-NNN-kebab-title.md` (three-digit, zero-padded number; lowercase kebab-case title). See `docs/adr/README.md` for the full template, status values, and the index of existing ADRs. Write one when picking between reasonable alternatives or when the *why* is non-obvious from the code; update the index table in the same commit.

### Formatting

Run `make format` after code changes. This runs `black` + `ruff check --fix`. Fix any remaining ruff errors manually.

### Commit messages

Generate commit messages via the `caveman:caveman-commit` skill. Conventional Commits, imperative subject ≤50 chars, body only for non-obvious *why*. No AI attribution trailers.

### Testing

Tests run via `make test-docker` in Docker, not locally. Test structure mirrors `backend/`: `tests/api/`, `tests/services/`, `tests/repositories/`, `tests/models/`.

`make test-docker` binds port 5433. If another repo/worktree already runs `aide-db-test-1` on 5433, stop it first: `docker stop aide-db-test-1`. Only one test DB instance at a time.

Narrow scope: `PYTEST_ARGS="-v tests/path/test_file.py" make test-docker` (passes args to pytest inside the container).

Test layer patterns: **API/repo tests** use the `transactional_session` fixture from `tests/conftest.py` (real DB, rolls back per-test). **Service tests** use mocked UoW — see `_MockUnitOfWork` / `_MockRepository` in `tests/services/test_system_kind_service.py`.

API tests with auth: use `httpx.AsyncClient` with `ASGITransport(app=app)` (sync `TestClient` won't authenticate). Build a `superuser` fixture (creates a `User`, hashes password) and a `headers` fixture that POSTs `/api/v1/login/` with form data and returns `{"Authorization": f"Bearer {token}"}`. Pattern sample: `tests/api/test_dataset_links.py`.

Test helper duplication: `_make_system(session, code_suffix)` and `_create_dataset(...)` / `_create_field(...)` are currently inlined in multiple test files. No shared `seeded_system` fixture. When adding a 3rd copy of one of these helpers, consider promoting to `tests/conftest.py` or `tests/_helpers.py`.

After changing deps (`uv sync`) or adding a new local workspace package, rebuild the test image: `docker compose build test`. Otherwise `make test-docker` fails with `ModuleNotFoundError`.

SDK and crawler tests run standalone: `cd sdk && uv run pytest tests/` and `cd crawler && uv run pytest tests/` — no DB needed.

Scope a coverage run: `PYTEST_ARGS="--cov=backend.services.X --cov-report=term-missing tests/services/test_X.py" make test-docker`. Use this when writing new tests to verify branch coverage. Note: very narrow `--cov` paths (e.g. a single module) can reproducibly segfault asyncpg in this Docker test runner — fall back to `--cov=backend` if you hit a segfault.

### Alembic migrations

After `make alembic-gen`, review the generated file. Auto-generate picks up pre-existing schema drift (nullability mismatches, missing indexes). Strip unrelated operations before committing — keep each migration focused on one model change.

### Local package CLI scripts

For packages with `[project.scripts]` (e.g. `crawler/`), add hatchling build-system so `uv` installs the entry point:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["package_name"]
```

### Data type seeding

Data types are pre-loaded per flavor from YAML files in `backend/scripts/data/`. Flavor `code` = min supported version; `versions` lists all compatible versions. Re-run `seed_data_types.py` after editing a YAML — it is idempotent. Removing a type from YAML does NOT delete the row (protects existing `TypeInstance` FKs); prune manually if required.

### Known quirks

- `BaseResource.list` shadows the `list` builtin inside the SDK class scope — use `typing.List[X]` (not `list[X]`) for type annotations on methods of `sdk/aide_sdk/resources/base.py`.
- Pre-existing mypy errors in `backend/scripts/_seed_core.py` (yaml stubs) and `sdk/aide_sdk/resources/datasets.py` (type assignment) are unrelated to most work — ignore when evaluating your diff.
- SQLAlchemy `flush()` on PG populates server-generated columns (id, timestamps, row_version) via RETURNING — no explicit `refresh()` needed for `add_all` + `flush` batch inserts.
- SQLAlchemy mapper config triggers on first flush, not lazily — forward-ref relationships (`relationship("UnbornClass", ...)`) fail with `InvalidRequestError` at write time. Both sides of a back-populating relationship must exist in the same commit.
- `make alembic-gen` binds port 5432. If user's `aide-db-1` runs on 5432, stop it first: `docker stop aide-db-1`; restart after with `docker start aide-db-1`.
- `get_filter_sort_dependency(filter_model, sortable, default)` asserts at route-registration: `filter_model=None` breaks. Always provide a Pydantic filter class. `sortable` must be `set[str]` (not tuple) to match the signature.
- Pydantic `*Base` field added before the matching SA column breaks polymorphic create via `DatasetService.create` (`model_class(**obj_in.model_dump())` → `TypeError` on unknown kwarg). Land schema field and column in the same commit.
- Async tests touching lazy relationships (`row.children`, `row.fields`) raise `MissingGreenlet`. Use `selectinload(Parent.children)` in the test query when the relationship isn't `lazy="selectin"` in the model.
- New modules with `import yaml` need `# type: ignore[import-untyped]` — PyYAML has no stubs. Matches existing pattern in `backend/scripts/_seed_core.py`.
- After re-pin of `DatasetLink`, the compat report may show `source_unbound` / `target_unbound` for `FieldLink` rows whose fields have no binding in the new pinned schemas. Expected — operator deletes them as part of the pin transition.
- `Field.origin` transitions are atomic with `FieldLink` create/delete in a single UoW. `PATCH /fields/{id}` with `origin: "deprecated"` while the field still has an active inbound `FieldLink` returns `409 FIELD_ORIGIN_CONFLICT`.
- Lineage-pin Migration B (`add_lineage_pins_b_finalize`) downgrade is **unsafe** once `DEPRECATED` fields exist — `deprecated` maps back to `is_tech=False` (mapped), violating the "mapped target needs source" invariant. Hold Migration B until the forward direction is confirmed stable.
- Route ordering in `backend/api/v1/dataset_links.py`: the `/compat` (bulk) route must be declared **before** `/{obj_id}` variants so FastAPI does not interpret `compat` as a UUID path parameter.
- Lockstep bump of `aide-schemas`, `aide-sdk`, `aide-crawler` at any breaking schema change. No dual-support transitional acceptance of old field names (`is_tech` removed, not deprecated in place).
- Lake-sync (`POST /datasets/{id}/lake-sync`) is atomic: any failure rolls back the whole UoW; partial target chains never observed. Re-running with the same target returns 409 `DATASET_ALREADY_EXISTS`; recreate by deleting `DatasetLink` first (RESTRICT FK on schema pins), then the target `Dataset`.
- `LAKE_SYNC_AMBIGUOUS_CAST` carries `details={"field": ..., "candidates": [...]}` via `AppException.details` (added in this phase). The endpoint's response body includes a top-level `details` key when populated — the SDK contract relies on it. Remediate ambiguity by adding the field to `request.overrides`.
- Lake-sync overrides are leaf-only. For `array<X>` source, `override.data_type_code="list"` produces `list<X-resolved>`; the inner element type cannot be overridden in MVP — it comes from the source-resolved cast rule.
- `tech_type_resolver.yaml` is loaded at backend module-load time via `TechTypeResolver.from_yaml(...)` in `backend/services/dataset.py` — **not** DB-seeded. Adding a flavor branch (e.g. `iceberg_v2`) requires a backend restart, not a re-seed.
- Iceberg type catalog (`iceberg_v2.yaml`) is canonical to Apache Iceberg v2 spec. v3-only types (`unknown`, `variant`, `geometry`, `geography`, `timestamp_ns`, `timestamptz_ns`) belong in a future `iceberg_v3` flavor, not `iceberg_v2`.
- Slot rename `array.item → list.element` lives in `_SLOT_RENAMES_BY_TARGET_CODE` constant in `backend/services/lake_sync_resolver.py`. Only known cross-flavor child-slot rename in v2; add new entries here when target aggregate types diverge.
- Lake-sync's source-side `TypeInstance` tree eager-load is depth-3 (`backend/services/lake_sync.py:_load_bindings`). Source trees nested deeper than 3 levels (e.g. `array<struct<list<...>>>`) trigger `MissingGreenlet`. Acceptable for current sources (depth ≤ 2). Future deepening requires a recursive eager-load or CTE refactor.
