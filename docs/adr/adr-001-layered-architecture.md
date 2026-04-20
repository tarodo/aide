# ADR-001: Layered Architecture — Router → Service → UoW → Repository → Model

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

AIDE is a metadata catalog backed by a single PostgreSQL database with a
non-trivial entity graph (systems, datasets, fields, type instances,
credentials, etc.). The backend serves REST endpoints, performs cross-entity
validation (e.g. a `System` must refer to an existing `SystemFlavor`), and
must support transactional writes that span multiple tables.

A new contributor opening the repository needs to know, without reading every
file, **where each kind of code belongs**:

- Where do HTTP concerns live (routing, status codes, request parsing)?
- Where does business logic live (validation, cross-entity rules, version
  checks)?
- Where does database access live (SQL, filtering, pagination)?
- How are transactions scoped across multiple repository calls in one
  request?

Without an explicit contract, logic tends to drift into routers (fat
controllers) or models (anemic services + magic ORM hooks), both of which
make the codebase hard to evolve and test.

## 2. Options Considered

### Option A: Explicit 5-layer pipeline (Router → Service → UoW → Repository → Model) — **chosen**

Each layer has a narrow contract and may only call the layer below it.
SQLAlchemy 2.0 async ORM sits at the bottom; FastAPI sits at the top.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium — five layers, explicit plumbing per entity |
| Testability | High — each layer mockable in isolation (service tests mock UoW; repo tests use real DB) |
| Consistency | High — every entity follows the same shape |
| Cost of adding an entity | Medium — model + repo + service + router + schema + migration |
| Coupling | Low — layers depend only on the layer immediately below |

**Pros:**

- Clear ownership per layer; code reviews can reject "wrong-layer" logic on
  sight.
- Cross-entity business rules have a single home (service `_pre_create` /
  `_pre_update` / `_pre_delete` hooks) rather than being split between route
  handlers and DB triggers.
- Transactions scope naturally to a request via the UoW context manager.
- Generic base classes (`BaseRepository[M]`, `GenericService[M,C,U,R]`)
  absorb CRUD boilerplate — see ADR-002.

**Cons:**

- More files per entity than a "flat FastAPI" layout.
- Requires discipline: it is tempting to reach for `session.execute()` from
  a route handler.
- Learning curve for contributors used to frameworks where service/repo
  layers are implicit.

### Option B: FastAPI-direct (route handlers own session + SQL)

Every route handler takes `session: AsyncSession = Depends(get_session)`
and writes SQL inline. No separate service or repository layer.

**Pros:** fewer files; low ceremony for simple CRUD.
**Cons:** cross-entity rules duplicate across routes; service behaviour is
not testable without spinning up FastAPI; routes become long once validation
grows; no natural place for reusable business logic (e.g. the `_pre_delete`
dependent-count check).

### Option C: Django-style fat models (business logic on ORM classes)

Validation and cross-entity rules live as methods on SQLAlchemy model
classes; route handlers instantiate and call them directly.

**Pros:** entity-centric code, easy to follow "what can a `System` do?".
**Cons:** couples HTTP-layer concerns (error codes, permissions) to the ORM;
async SQLAlchemy does not make ActiveRecord-style APIs pleasant; version
checks and permission logic become hard to share across entities.

## 3. Trade-off Analysis

The core tension is **boilerplate vs. discipline**. A flatter design (Option
B) ships the first endpoint faster but rewards duplication by the fifth
entity. A fat-model design (Option C) concentrates logic but blurs HTTP
concerns into the persistence layer.

Option A pays an up-front complexity cost that amortizes as entities
multiply: each new resource follows a known rhythm, and 15+ entities already
benefit from the generic bases (ADR-002).

## 4. Recommendation

Adopt the explicit 5-layer pipeline (Option A). Canonical request flow:

```
HTTP request
   │
   ▼
Router (backend/api/v1/*.py)
   │   - Parse & validate request (Pydantic)
   │   - Auth / permission dependencies
   │   - Return HTTP status + response schema
   ▼
Service (backend/services/*.py)
   │   - Business logic, cross-entity validation
   │   - Orchestrates one logical operation per method
   │   - Receives a UoW, uses `async with uow:` to scope a transaction
   ▼
Unit of Work (backend/db/uow.py)
   │   - Opens an AsyncSession on __aenter__
   │   - Commits on clean exit, rolls back on exception
   │   - Holds a registry of pre-instantiated repositories
   ▼
Repository (backend/repositories/*.py)
   │   - SQL generation (SQLAlchemy 2.0 select/update/delete)
   │   - Filtering, sorting, pagination primitives
   │   - No business rules, no cross-entity logic
   ▼
Model (backend/models/*.py)
       - SQLAlchemy 2.0 declarative ORM
       - Columns, relationships, mixins (UUID, timestamps, soft-delete)
```

## 5. Implementation Notes

### Layer contracts

**Router layer (`backend/api/v1/`)** — `APIRouter` definitions only.

- Build endpoints either via `create_crud_router` (for standard CRUD) or as
  hand-written `@router.get / @router.post` functions.
- Inject the service and UoW as FastAPI dependencies:
  ```python
  service: SystemService = Depends(SystemService)
  uow: UnitOfWork = Depends(UnitOfWork)
  ```
- Allowed imports: `backend.services.*`, `backend.schemas.*`,
  `backend.core.errors`, `backend.api.dependencies`, `backend.db.uow`
  (for type hints only).
- **Not allowed:** direct SQLAlchemy calls, direct `session.execute(...)`,
  raw SQL, importing from `backend.repositories.*` or `backend.models.*`.

**Service layer (`backend/services/`)** — subclass `GenericService` or
`SoftDeleteService` (see ADR-002).

- Public methods take `uow: UnitOfWork` as an argument and use
  `async with uow:` internally to scope a transaction.
- Use `self._get_repository(uow.session)` to access the entity's own
  repository; use `uow.<other_entity>s` (pre-instantiated in the UoW) when
  checking foreign-key targets across entities.
- Override `_pre_create`, `_pre_update`, `_pre_delete` for entity-specific
  validation. Raise `AppException(error_code)` — never `HTTPException`
  (see ADR-005).
- Ad-hoc read-only queries that are local to a single validation step
  (dependent-child counts, existence probes) may be issued directly via
  `uow.session.execute(...)` inside a `_pre_*` hook. If the same query
  appears in a second service, promote it to a method on the target
  repository instead of duplicating the SQL.
- Allowed imports: everything except `fastapi` and the routers.

**Unit of Work layer (`backend/db/uow.py`)** — session + repository registry.

- Single async context manager per request. `__aenter__` opens an
  `AsyncSession` and instantiates every repository bound to it.
- `__aexit__` commits on success, rolls back on exception, then closes.
- UoW is injected as `Depends(UnitOfWork)` by FastAPI — a fresh instance
  per request. Do not share UoW across requests.

**Repository layer (`backend/repositories/`)** — SQL generation only.

- Each repo extends `BaseRepository[Model]` (or `SoftDeleteRepository`
  for soft-deletable entities).
- Use the inherited `_execute`, `_apply_filters`, `_apply_sort` helpers —
  they carry slow-query logging and the filter/sort DSL.
- **Not allowed:** raising `AppException`, importing from
  `backend.services.*` or `backend.api.*`, mutating fields that are the
  service's responsibility (e.g. `row_version`, `updated_by`, timestamps).

**Model layer (`backend/models/`)** — SQLAlchemy 2.0 declarative classes.

- Column definitions, relationships, mixins, hybrid properties.
- **Not allowed:** business rules, validation beyond DB constraints,
  database-side triggers encoding business logic.

### Adding a new entity — canonical checklist

1. `schemas/aide_schemas/<entity>.py` — Pydantic `Create`, `Update`, `Read`,
   filter schema; re-export from `backend/schemas/<entity>.py`.
2. `backend/models/<entity>.py` — SQLAlchemy model with appropriate mixins.
3. `backend/repositories/<entity>.py` — subclass `BaseRepository`
   (or `SoftDeleteRepository`); add custom query helpers as needed.
4. Register the repository as an attribute on `UnitOfWork.__aenter__`.
5. `backend/services/<entity>.py` — subclass `GenericService` /
   `SoftDeleteService`; override `_pre_*` hooks for validation.
6. `backend/api/v1/<entity>.py` — router via `create_crud_router` or custom
   endpoints.
7. `backend/main.py` — `app.include_router(...)` with `/api/v1/<resource>`
   prefix and tag.
8. `make alembic-gen` → review migration → commit.
9. `docs/AIDE_data_model.json` — update ER diagram (per CLAUDE.md).

### What must NOT happen

- `session.execute(...)` in a router file. Move it into a repository.
- `raise HTTPException(...)` in a service file. Raise `AppException(code)`
  and let the global handler map it (ADR-005).
- Business validation in a repository (e.g. "reject if parent has
  children"). That belongs in the service `_pre_delete`.
- Instantiating a repository directly in a router. Inject the service.

## 6. Consequences

- **Easier:** adding a new resource is mechanical once the pattern is
  internalized; reviewers can reject misplaced logic quickly; unit tests
  can mock at the correct seam (see ADR-007).
- **Harder:** simple one-file scripts inside the backend package must still
  go through the UoW to share the session lifecycle; deviating for
  experiments is discouraged.
- **Revisit when:** we split the backend into multiple services, or when
  we introduce a second persistence engine (e.g. an event store) that does
  not fit the UoW/AsyncSession contract.
