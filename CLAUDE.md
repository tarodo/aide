# AIDE Metastore

Contract-first metadata registry: FastAPI backend + shared Pydantic DTOs + async SDK + RDBMS crawler. Package manager `uv`, Python ≥ 3.13.

## Commands

| Command | Purpose |
|---------|---------|
| `make up` / `make stop` | Compose: app on :8000 + DB; runs migrations and superuser bootstrap |
| `make run` | Local uvicorn on :8001 (reads `.env`) |
| `make check` | ruff + black --check + mypy (red by design — see Gotchas) |
| `make format` | black + ruff --fix; run after every code change |
| `make test-docker` | Backend tests in Docker — the only supported way (see Testing) |
| `make build-test` | Rebuild test image after `uv sync` or a new workspace package |
| `make alembic-gen MSG="..."` | Autogenerate migration; review before commit |
| `make alembic-head` | Apply migrations |
| `make seed-data-types` | Seed postgres14 types; other flavors: `docker compose run --rm app python -m backend.scripts.seed_data_types --file backend/scripts/data/iceberg_v2.yaml` |
| `cd sdk && uv run pytest tests/`, `cd crawler && uv run pytest tests/` | SDK / crawler tests, no DB |

Makefile has a `%:` catch-all: a misspelled target exits 0 with no output — check the target name when a step prints nothing.

## Architecture

Monorepo of 4 packages wired via `[tool.uv.sources]`; dependency direction `schemas ← backend` and `schemas ← sdk ← crawler`:
- `backend/` — FastAPI metastore. Root `pyproject.toml` *is* the backend package (no `backend/pyproject.toml`).
- `schemas/` — `aide-schemas`, shared Pydantic DTOs, zero backend deps.
- `sdk/` — `aide-sdk`, async httpx client. `crawler/` — `aide-crawler`, RDBMS crawler CLI.

Request flow: `api/v1` router → `services` → `db/uow.py` (UnitOfWork) → `repositories` → `models`. Why: ADR-001..005 in `docs/adr/`.

Entities share one stem across layers: `models/x.py`, `repositories/x.py`, `services/x.py`, `schemas/aide_schemas/x.py` + shim `backend/schemas/x.py`, `api/v1/xs.py`, `sdk/aide_sdk/resources/xs.py`. Cross-cutting flows that break the stem rule:

| Flow | Modules |
|------|---------|
| Compat pre-flight | `services/dataset_link_compat.py`, DTOs `lineage_compat.py`, routes in `api/v1/dataset_links.py` (ADR-018) |
| Lake-sync | `services/lake_sync.py`, `lake_sync_resolver.py`, `core/tech_type_resolver.py` (ADR-019) |
| Engines / render-sql | `services/engine.py`, `engine_compatibility.py`, `engine_render_service.py`, `engine_render/`, `envelope_resolver.py` (ADR-020) |
| List filters | `api/filter_sort.py` + `backend/schemas/filters.py` (backend-only, not in aide_schemas) (ADR-014) |

### Adding an entity
1. Model; update `docs/AIDE_data_model.json` (ChartDB ER diagram) in the same commit.
2. Repository; register it as an attribute in `UnitOfWork.__aenter__` (`backend/db/uow.py`) and mirror it on `_MockUnitOfWork` in service tests.
3. DTOs in `schemas/aide_schemas/`; shim in `backend/schemas/` as `from aide_schemas.x import Y as Y` (alias form = explicit re-export for mypy/ruff).
4. Service, router, `include_router` in `backend/main.py`, SDK resource.
5. Error codes: constant + `ERROR_MAP` entry in `backend/core/errors.py` + the route's `*_error_codes` list. An unmapped code is served as 500.
6. Land a Pydantic `*Base` field and its SA column in the same commit — polymorphic create does `model_class(**obj_in.model_dump())`.

## Environment

Three env files, each copied from its `*.example`: `.env` (local `make run`, alembic, pytest), `backend.env` (compose `app`), `db.env` (compose `db` / `db-test`). Key vars: `DATABASE_URL`, `JWT_SECRET_KEY`. `make up` fails at project load when `backend.env` or `db.env` is missing.

## Conventions

- Enum-like columns are `String(N)` validated by one `str, enum.Enum` shared by model and Pydantic schema (ADR-010). PostgreSQL native enums are out.
- `deleted_at` and other mixin timestamps are naive UTC: `datetime.now(timezone.utc).replace(tzinfo=None)`; asyncpg rejects aware values (ADR-006).
- Soft-delete is per mixin: models with `SoftDeleteMetaDataMixin` need `if x is None or x.deleted_at is not None` on lookup; `MetaDataMixin` models only `is None`. Check the model's mixin, not the entity name.
- Every `*Update` DTO requires `row_version` (optimistic lock, ADR-009); polymorphic updates (datasets, engines) also require `kind`. GET first, echo both back.
- Auth defaults differ by router style: `create_crud_router` = public reads, any active user writes, superuser delete/restore. Hand-written routers (e.g. `api/v1/datasets.py`) add `Depends(get_current_superuser)` on writes explicitly — follow the router you are editing.
- Declare static sub-routes (`/compat`, `/tree`) before `/{obj_id}` in a router.
- Breaking DTO change = lockstep version bump of `aide-schemas`, `aide-sdk`, `aide-crawler`; old field names are removed outright.
- ADRs: `docs/adr/adr-NNN-kebab-title.md`; update the index in `docs/adr/README.md` in the same commit. Write one when choosing between reasonable alternatives or when the *why* is non-obvious from code.
- Commits: Conventional Commits, imperative subject ≤ 72 chars, body states the *why* for `fix` / `refactor`. No AI attribution trailers or footers.

## Testing

- Backend tests run only via `make test-docker` (port 5433). Bare `uv run pytest` / `make test-local` run `alembic upgrade head` + `downgrade base` against the `.env` `DATABASE_URL` — that wipes the dev DB.
- Every migration needs a working `downgrade()`: the session fixture downgrades to base at teardown, and a broken one poisons `aide_test` for the next run.
- Narrow scope: `PYTEST_ARGS="-v tests/api/test_x.py" make test-docker`. Coverage: `PYTEST_ARGS="--cov=backend --cov-report=term-missing tests/services/test_x.py" make test-docker` (a very narrow `--cov` path can segfault asyncpg — widen to `--cov=backend`).
- Another checkout holding `aide-db-test-1` on 5433 blocks the run: `docker stop aide-db-test-1` (a worktree names it `<dir>-db-test-1`).
- API tests: `httpx.AsyncClient(transport=ASGITransport(app=app))` with per-file `superuser` + `superuser_token_headers` fixtures (sample: `tests/api/test_dataset_links.py`). The sync `client` fixture cannot authenticate. Routers take `Depends(UnitOfWork)` so the autouse `transactional_session` override applies.
- Service tests: mocked UoW — `_MockUnitOfWork` / `_MockRepository` in `tests/services/test_system_kind_service.py`. Lake-sync helpers live in `tests/_helpers.py`.
- Login is rate-limited 5/min per IP and the limiter resets per test: reuse the headers fixture instead of logging in in a loop.
- Async access to a relationship without `selectinload` raises `MissingGreenlet`; no model sets `lazy=`, so eager-load explicitly in test queries.

## Gotchas

- `make check` is red by design: 2 pre-existing mypy errors (`backend/scripts/_seed_core.py:8`, `sdk/aide_sdk/resources/datasets.py:9`). Ignore them when evaluating your diff.
- `import yaml` needs `# type: ignore[import-untyped]` (sample: `backend/core/tech_type_resolver.py`).
- `AsyncSessionLocal` has `autoflush=False`: after `session.add()` call `await session.flush()` before a query expects the row (`BaseRepository.create/update` flush for you).
- `UnitOfWork` is not re-entrant — `__aexit__` commits and closes. Inside `async with uow:` call `_impl`-style helpers that take the entered uow.
- `make alembic-gen` starts the compose `db` on 5432 (stop a foreign `aide-db-1` first) and picks up pre-existing drift — strip unrelated ops so each migration is one model change.
- Seeding order: `seed_data_types` for postgres14 **and** iceberg_v2 → `seed_cast_rules` → `seed_tech_templates` (LookupError otherwise). `seed_tech_templates` inserts only — existing template fields keep old values. Removing a type from a YAML never deletes the row (protects `TypeInstance` FKs).
- `tech_type_resolver.yaml` loads at backend import time: edit → restart, not re-seed.
- `get_filter_sort_dependency(filter_model, sortable_fields: set[str], default_sort)` — always pass a filter class; `filter_model=None` breaks route registration. Filter fields use `__like/__in/__gte/__lte`; `__in` is a comma-separated string.
- SDK: `BaseResource.list` shadows the builtin — use `typing.List[X]` in that file. `BaseResource.update` sends PUT while `datasets`, `engines`, `dataset_links`, `field_links`, `tech_field_templates` routes are PATCH-only (405). `AideApiError` drops the response `details` payload.
- Crawler `GENERIC_TYPE_MAP` is an isinstance-ordered chain — insert SA subclasses before their parent; dialect types go in `DIALECT_TYPE_MAP` keyed by `(dialect, ClassName)`.
- Root `.venv` contains only `aide-schemas`: run `aide-crawler` and SDK/crawler tests from `crawler/` / `sdk/` (own `uv.lock`).
- `DatasetSchema.schema` is `schema_` in Pydantic (JSON key `schema`); `DatasetSchemaService` hand-renames it in create/update.
- Eager-load depth is fixed: lake-sync source `TypeInstance` tree = 3, `/fields/tree` = 5. Deeper nesting → `MissingGreenlet` → 500 (ADR-019).
