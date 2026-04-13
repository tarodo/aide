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

Package manager: `uv`. Python ≥ 3.13.

## Architecture

Layered async FastAPI app:

```
backend/
├── api/v1/          # FastAPI routers (REST endpoints)
├── services/        # Business logic (GenericService base)
├── repositories/    # DB access (BaseRepository generic CRUD)
├── models/          # SQLAlchemy 2.0 async ORM
├── schemas/         # Pydantic DTOs (Create/Read/Update)
├── core/            # Config, auth, errors
├── db/              # Session, UoW pattern
└── alembic/         # Migrations
```

Request flow: Router → Service → UoW → Repository → Model.

New entities follow this pattern: add model, repository, service, schemas, router, then wire in `main.py`.

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

### Data model documentation

When adding or modifying SQLAlchemy models, update `docs/AIDE_data_model.json` (ChartDB format) to keep the ER diagram in sync. Add/update tables, fields, and relationships matching the model changes.

### Formatting

Run `make format` after code changes. This runs `black` + `ruff check --fix`. Fix any remaining ruff errors manually.

### Testing

Tests run via `make test-docker` in Docker, not locally. Test structure mirrors `backend/`: `tests/api/`, `tests/services/`, `tests/repositories/`, `tests/models/`.
