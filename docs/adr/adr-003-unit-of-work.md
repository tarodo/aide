# ADR-003: Unit of Work Pattern and Session Lifecycle

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

AIDE speaks to PostgreSQL through SQLAlchemy 2.0's async engine. Every HTTP
request needs:

1. A single database **session** (a short-lived, stateful connection
   abstraction) for its duration.
2. A **transaction** scope for each logical operation — a create, an update,
   a multi-step validation + write — with a clean commit/rollback boundary.
3. Access to **multiple repositories** that share that session so their
   work participates in the same transaction.
4. **Cleanup**: the session must be returned to the pool on both the
   happy path and on every failure mode (business exception, validation
   error, cancelled request).

Doing this with a raw `AsyncSession` per endpoint pushes plumbing into
every route and service: open a session, wrap every write in
`try/except/commit/rollback`, remember to close it. It is easy to leak
sessions, forget a rollback on exception, or accidentally use two
sessions in the same request and observe inconsistent reads across them.

We need one object that owns session lifecycle, transaction boundary, and
the registry of repositories for a given unit of work.

## 2. Options Considered

### Option A: Explicit `UnitOfWork` as a FastAPI dependency + service-managed context — **chosen**

`UnitOfWork` is a plain class with `__aenter__` / `__aexit__`. FastAPI
injects a fresh instance per request via `Depends(UnitOfWork)`. The
**service** enters the context (`async with uow:`) around one logical
operation; the UoW commits on clean exit and rolls back on any exception.

| Dimension | Assessment |
|-----------|------------|
| Transaction clarity | **High** — `async with uow:` block = one transaction |
| Session leaks | **Low risk** — `__aexit__` always closes |
| Cross-repository atomicity | **Native** — all repos share `uow.session` |
| Boilerplate | **Low** — one line per service method |
| Testability | **High** — easy to substitute a fake UoW (see ADR-007) |

**Pros:**

- Transaction boundaries are visible in code — any reader can point at
  the `async with uow:` and say "this is the unit of work".
- Rollback is automatic on any raised exception, including
  `AppException` from validation hooks.
- The repository registry (`uow.users`, `uow.systems`, ...) lets a
  service reach into other entities without importing 15 repository
  classes or manually threading the session.
- Works uniformly inside request dependencies (`get_current_user`) and
  service methods.

**Cons:**

- Re-entering the same UoW instance opens a **new** session each time
  (see the notes below) — contributors must know this.
- The UoW class imports every repository, so a new entity must remember
  to register itself in `__aenter__`.
- Two `async with uow:` blocks in the same request are two separate
  transactions — a fact that is easy to miss.

### Option B: FastAPI `get_session` dependency + explicit `session.begin()`

A dependency yields an `AsyncSession`; handlers or services wrap every
write in `async with session.begin():`.

**Pros:** closer to the SQLAlchemy stock pattern; no custom class.
**Cons:** every service method re-writes the transaction boilerplate;
there is no place to hang the repository registry; cross-entity checks
instantiate repositories ad hoc.

### Option C: Ambient session via `contextvars` + decorator-driven transactions

A global session is installed into a `ContextVar` at request start and
unwrapped wherever needed; transactions are opened via a `@transactional`
decorator on service methods.

**Pros:** minimal argument threading; service methods look pure.
**Cons:** hidden state is hostile to debugging; decorator magic obscures
where the transaction begins; unit tests that do not set up the
`ContextVar` will silently share a global session and mask bugs.

## 3. Trade-off Analysis

The key tension is **explicitness vs. ceremony**. Option C minimises
boilerplate but hides the transaction boundary. Option B keeps the
boundary visible but forces every service to carry the same try/commit/
rollback scaffolding. Option A pays a small ceremony cost
(`async with uow:`) in exchange for a transaction boundary that is both
explicit and symmetrical on entry and exit.

## 4. Recommendation

Adopt Option A. Use `UnitOfWork` as both the session owner and the
repository registry. Enter it exactly at the point where a transaction
must begin — typically the top of a service method.

## 5. Implementation Notes

### The UnitOfWork class

[`backend/db/uow.py`](../../backend/db/uow.py) defines `UnitOfWork`:

```python
class UnitOfWork:
    def __init__(self) -> None:
        self.session_factory = AsyncSessionLocal

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self.session_factory()
        self.users = UserRepository(self.session)
        self.systems = SystemRepository(self.session)
        # ... all other repositories ...
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
        await self.session.close()
```

`AsyncSessionLocal` is an `async_sessionmaker` configured with
`autocommit=False, autoflush=False` in
[`backend/db/session.py`](../../backend/db/session.py) — we want full
control over when data is flushed and committed.

### Injecting the UoW

Always inject via FastAPI:

```python
async def endpoint(
    uow: UnitOfWork = Depends(UnitOfWork),
    service: SystemService = Depends(SystemService),
) -> SystemRead:
    return await service.create(uow, payload, creator_id=user.id)
```

Services take the UoW as an argument and enter it internally — they do
**not** create a UoW themselves. This keeps the session factory
replaceable in tests.

### Transaction boundary

Every service method that touches the database wraps its work in:

```python
async with uow:
    repo = self._get_repository(uow.session)
    await self._pre_create(uow, obj_in, creator_id)
    ...
```

Leaving the block cleanly → `commit`. Leaving it via exception (including
`AppException` from a `_pre_*` hook) → `rollback`, then close. There is
no need — and no right time — to call `uow.commit()` or
`uow.rollback()` manually from a service.

### Multiple `async with` blocks per request

FastAPI's dependency cache returns the **same UoW instance** to every
`Depends(UnitOfWork)` within one request. That instance, however, opens a
**new session** each time `__aenter__` runs. A typical request looks
like:

```
Request
 ├─ get_current_user                 (async with uow: … expunge … exit)  # session A
 └─ SystemService.create(uow, ...)   (async with uow: …         exit)   # session B
```

These are two separate transactions, not one. Do not rely on writes in
an earlier dependency being visible as uncommitted reads in a later
service call — they will not be; the earlier session has already
committed and closed.

If atomicity is required across multiple service calls, compose them
into a single service method and enter the UoW once.

### The `expunge` pattern in auth dependencies

[`backend/api/dependencies.py`](../../backend/api/dependencies.py)
`get_current_user` loads the `User`, touches lazy-loaded attributes
while the session is still open, and then calls
`uow.session.expunge(user)` before returning. This detaches the ORM
instance so downstream code can read its attributes after the session
closes without hitting `DetachedInstanceError`. The UoW will still
commit (no-op for a read) and close on exit.

This pattern is only necessary when an ORM object must survive past the
`async with` block. Services that return Pydantic DTOs do not need it —
`model_validate` runs inside the block and the DTO is detached by
construction.

### Registering a new entity's repository

When adding a new entity (ADR-001 §5), append one line to
`UnitOfWork.__aenter__`:

```python
self.my_entities = MyEntityRepository(self.session)
```

This makes `uow.my_entities` available to every service method for
cross-entity validation.

### Rollback behaviour and exception types

Any exception escaping the `async with uow:` block triggers rollback:

- `AppException` from a validation hook — **rolls back**, propagates up
  to the global handler, which emits the HTTP error (see ADR-005).
- SQLAlchemy `IntegrityError`, asyncpg errors — **roll back**, propagate
  as the `Exception` fallback handler's 500, with the stack captured in
  the structured log.
- `asyncio.CancelledError` (client disconnected) — **rolls back**,
  propagates as cancellation.

There is no exception that commits.

## 6. Consequences

- **Easier:** writing a transactional service method — one `async with`
  and done. Adding a new cross-entity check — reach for
  `uow.<target_entity>s`.
- **Harder:** sharing a transaction across two service methods in the
  same request (by design — compose them into one method instead).
- **Revisit when:** we introduce read-only endpoints that can run without
  a session altogether, or when we need explicit savepoints inside a
  service method (SQLAlchemy supports them via `session.begin_nested()`
  but we do not use them yet).
