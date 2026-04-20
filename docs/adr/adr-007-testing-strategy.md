# ADR-007: Testing Strategy — Per-Layer Fixtures and Isolation

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

The layered architecture (ADR-001) gives us three distinct sites worth
testing:

- **API** — HTTP contract, serialization, auth, error envelope.
- **Service** — business logic, cross-entity validation, version checks,
  permission rules.
- **Repository** — SQL generation, filter/sort/pagination semantics,
  soft-delete behaviour.

Each layer has its own failure modes, and the right test seam differs by
layer:

- Testing a service with a real database pulls in migrations, seeded
  reference data, and FK constraints that have nothing to do with the
  business rule under test — the test suite becomes slow, flaky, and
  harder to read.
- Testing a router with mocks drops exactly the integration behaviour
  that matters at the HTTP boundary: session lifecycle, auth
  dependencies, JSON envelopes, error code → status mapping.
- Testing SQL strings against a mock session verifies shape but not
  behaviour (index usage, constraint names, soft-delete filtering) —
  sometimes that is enough, sometimes it is not.

We also need the suite to be **isolated per test** so failures do not
contaminate each other, and **fast enough to run on every change**.

## 2. Options Considered

### Option A: Layered strategy — mock at the boundary below each layer; Docker-based DB for the DB-backed layers — **chosen**

- **API tests** exercise the full stack through FastAPI's `TestClient`
  against a **real PostgreSQL database** running in Docker. Each test
  is wrapped in a transaction that is rolled back on teardown so the
  database surface is unchanged between tests.
- **Service tests** use a `_MockUnitOfWork` and `_MockRepository` so the
  service layer runs in isolation with no database and no FastAPI.
- **Repository tests** come in two flavours: a mocked `AsyncSession`
  that asserts against the generated SQL statement, or the real
  `transactional_session` fixture for behavioural checks (soft-delete,
  constraint-driven returns).
- The test DB runs as a separate Docker service on port 5433; migrations
  run via Alembic once per session before tests, and downgrade after.

| Dimension | Assessment |
|-----------|------------|
| Speed | **Service tests are fast** (no DB); API tests amortise DB cost across many per run |
| Isolation | **High** — autouse transaction rollback; autouse rate-limit reset |
| Fidelity | **High at the boundary that matters per layer** |
| Setup complexity | **Medium** — Docker + Alembic migrations + fixtures |
| Ability to run subset | **Native** via `PYTEST_ARGS` |

**Pros:**

- Each layer has a seam that is test-friendly without forcing the other
  layers to participate.
- The `transactional_session` fixture overrides the UoW via FastAPI's
  `dependency_overrides`, so every API request inside a test shares one
  rolled-back transaction — no leakage across tests.
- Running the suite in Docker (`make test-docker`) decouples developer
  machines from PostgreSQL versions, plugin sets, and local DB state.
- Service tests that mock the UoW run end-to-end in microseconds,
  encouraging contributors to cover branches thoroughly.

**Cons:**

- Two test patterns for repositories (mocked session vs. real session)
  must be chosen per file; the default is not obvious without this ADR.
- Test DB binds to a fixed port (5433) which collides across worktrees
  — the suite requires ensuring no other test DB instance is running.
- Rebuilding the Docker image is required after dependency changes
  (`uv sync`) before `make test-docker` will see the new modules.

### Option B: Single-level strategy — everything against a real DB via `TestClient`

**Pros:** one pattern to learn; maximum fidelity.
**Cons:** service-level unit tests inherit the full migration + seeding
cost; tight coupling between business rules and the state of seeded
reference data; slow feedback loop discourages thorough branch
coverage; failures point at service behaviour but are hard to localize.

### Option C: Fully mocked — no real DB in the suite; DB covered by an
external integration suite

**Pros:** maximum speed.
**Cons:** SQL bugs (missing indexes, wrong constraint names, incorrect
`WHERE` clauses for soft-delete) escape review; the "it compiles" fallacy
for SQL string asserts — two syntactically-identical queries can behave
differently at the engine; postgres-specific features (partial unique
indexes, server defaults) cannot be verified.

### Option D: SQLite in-memory instead of Postgres in Docker

**Pros:** no container; starts instantly.
**Cons:** we rely on Postgres-specific features (JSONB, partial unique
indexes for soft-delete, `TIMESTAMP WITHOUT TIME ZONE` semantics,
`asyncpg`-specific driver quirks). Testing on SQLite would pass in CI
and fail in production.

## 3. Trade-off Analysis

The layered approach accepts a small complexity cost (two repo patterns,
fixtures per layer) in exchange for matching the test seam to the thing
being tested. The alternatives either slow the suite until people skip
coverage (Option B), let SQL and schema bugs escape the suite (Option C),
or diverge from production persistence (Option D).

## 4. Recommendation

Adopt Option A. Each layer uses the test seam that fits it. The
`transactional_session` fixture and `_MockUnitOfWork` pattern are
canonical seams — do not invent new ones per file.

## 5. Implementation Notes

### Running the suite

- Default: `make test-docker` — builds the test image (if needed), spins
  up the `aide-db-test-1` container on port 5433, runs migrations,
  executes pytest with coverage, tears the container down.
- Narrow scope: `PYTEST_ARGS="-v tests/services/test_system_service.py"
  make test-docker` — arguments are forwarded to pytest inside the
  container.
- Port 5433 is shared across repo checkouts. If another worktree already
  runs `aide-db-test-1`, stop it first: `docker stop aide-db-test-1`.
  Only one test DB instance may run at a time.
- After changing dependencies (`uv sync`) or adding a new workspace
  package, rebuild the test image: `docker compose build test`. Without
  this step the container is stale and `make test-docker` fails with
  `ModuleNotFoundError`.
- SDK and crawler suites run standalone without Docker:
  `cd sdk && uv run pytest tests/` and
  `cd crawler && uv run pytest tests/`.

### Fixtures in `tests/conftest.py`

Three fixtures govern the suite and are all **autouse** — every test
gets them without declaring them:

- `run_migrations` (session scope): before the session, runs
  `alembic upgrade head` against the test database via the sync psycopg
  driver; after the session, downgrades to `base`. This ensures a clean
  schema per CI run.
- `_reset_rate_limits` (per test): resets the slowapi limiter state, so
  rate-limited login tests do not contaminate each other.
- `transactional_session` (per test): creates a fresh
  `create_async_engine` and `AsyncSession` bound to a connection with an
  open transaction; yields the session; rolls the transaction back and
  closes everything on teardown. It also installs
  `app.dependency_overrides[UnitOfWork]` so every UoW injected by
  FastAPI within the test uses that single transaction-bound session.

`client` (non-autouse): returns a `TestClient(app)`. The app is already
patched by `transactional_session` at request time.

### Service tests — mocked UoW

Service tests live in `tests/services/` and follow a fixed shape. See
[`tests/services/test_system_kind_service.py`](../../tests/services/test_system_kind_service.py)
as the canonical example.

Pattern:

```python
class _MockRepository:
    def __init__(self) -> None:
        self.get = AsyncMock()
        self.get_by_code = AsyncMock()
        # ... one AsyncMock per repo method used by the service

class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = AsyncMock()
        # For services that run ad-hoc session.execute (e.g. _pre_delete
        # dependent-entity counts), stub the chain:
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        self.session.execute.return_value = mock_result

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, *a) -> None:
        return None
```

In each test, patch the service's `_get_repository` method to return the
mock repository, then call the service method:

```python
with patch.object(service, "_get_repository", return_value=mock_repo):
    await service.create(uow=mock_uow, obj_in=payload, creator_id=user_id)
```

Assert on: the error code in a raised `AppException`, the arguments
forwarded to repository mocks, and the shape of the returned DTO. Do
not assert on detail strings (see ADR-005).

### API tests — real DB via `TestClient`

API tests live in `tests/api/` and use the `client` fixture. Because
`transactional_session` is autouse, every request made through `client`
executes against the transaction-bound session and is rolled back on
teardown.

Pattern:

```python
def test_create_system(client, superuser_token):
    resp = client.post(
        "/api/v1/systems",
        headers={"Authorization": f"Bearer {superuser_token}"},
        json={"code": "mydb", "name": "My DB", "flavor_id": str(flavor_id)},
    )
    assert resp.status_code == 201
    assert resp.json()["code"] == "mydb"
```

Fixtures for seeding prerequisite data (users, system kinds, flavors)
belong next to the test that needs them; pytest's fixture lookup climbs
to `tests/conftest.py` automatically.

### Repository tests — two patterns

**Pattern 1 — mocked `AsyncSession` (default for SQL-shape checks).**
Canonical example:
[`tests/repositories/test_system_kind_repository.py`](../../tests/repositories/test_system_kind_repository.py).
Inject an `AsyncMock` session, stub `session.execute(...).scalars()...`,
call the repo method, and assert that `session.execute` was called with
the expected `Select` statement. Works for verifying query shape;
does not exercise the database engine.

**Pattern 2 — `transactional_session` (behavioural checks).** Used when
the test needs to observe real engine behaviour — soft-delete filtering
under a partial unique index, returning-server-default columns,
constraint-driven exception surfaces. The test takes the
`transactional_session` fixture as an argument and instantiates the
repository against it.

Choose Pattern 2 when the assertion is about **what the database does**
(constraint fires, soft-delete row hides from `get_multi`, batch insert
populates server-generated columns) and Pattern 1 when the assertion is
about **what the query says**.

### Model / core / scripts tests

- `tests/models/` — behavioural model tests with `transactional_session`
  (e.g. mixin column defaults).
- `tests/core/` — pure unit tests for config parsing, error registry,
  log configuration.
- `tests/scripts/` — idempotency and YAML-parsing tests for the seeder
  (see the data type seeding convention in CLAUDE.md).

### What not to do

- Do not write a service test that hits the real database. If a test
  needs a real DB, it is an API test or a repository behavioural test
  in disguise — move it to the correct location.
- Do not rely on cross-test state. Every test starts with a pristine
  rolled-back transaction; never leave seeded data in place for the
  next test, and never use module-scoped DB fixtures.
- Do not mix fixture patterns in one test: either mock the session or
  use `transactional_session`, never both in the same test function.
- Do not run tests locally without Docker (`uv run pytest`) against the
  same database as the dev app — migrations will clash. Always go
  through `make test-docker`.
- Do not assert on error **detail** text (ADR-005). Assert on
  `response.json()["error_code"]` or `AppException.error_code`.

## 6. Consequences

- **Easier:** service tests stay fast; contributors can cover branches
  thoroughly without the DB overhead; SQL-shape bugs are caught at the
  repository level; HTTP contract bugs are caught at the API level.
- **Harder:** adding a new entity requires writing tests in three
  locations (API, service, repo as appropriate); the Docker dependency
  for the full suite is non-negotiable for backend work.
- **Revisit when:** the suite becomes slow enough to impede a commit
  cadence (parallelize API tests with pytest-xdist, or switch from
  per-test transactions to per-test schema reset), or when a new
  persistence engine joins PostgreSQL (its tests will need their own
  seam analogous to `transactional_session`).
