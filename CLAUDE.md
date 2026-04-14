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

### Package layout

Root `pyproject.toml` is the backend package (no separate `backend/pyproject.toml`). Add backend deps to the root file.

### Data model documentation

When adding or modifying SQLAlchemy models, update `docs/AIDE_data_model.json` (ChartDB format) to keep the ER diagram in sync. Add/update tables, fields, and relationships matching the model changes.

### Formatting

Run `make format` after code changes. This runs `black` + `ruff check --fix`. Fix any remaining ruff errors manually.

### Testing

Tests run via `make test-docker` in Docker, not locally. Test structure mirrors `backend/`: `tests/api/`, `tests/services/`, `tests/repositories/`, `tests/models/`.

`make test-docker` binds port 5433. If another repo/worktree already runs `aide-db-test-1` on 5433, stop it first: `docker stop aide-db-test-1`. Only one test DB instance at a time.

After changing deps (`uv sync`) or adding a new local workspace package, rebuild the test image: `docker compose build test`. Otherwise `make test-docker` fails with `ModuleNotFoundError`.

SDK and crawler tests run standalone: `cd sdk && uv run pytest tests/` and `cd crawler && uv run pytest tests/` — no DB needed.

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
