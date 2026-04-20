# ADR-009: Optimistic Locking via `row_version`

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

AIDE edits are mostly human-driven (admins tagging systems, crawler
operators amending dataset metadata) but are regularly concurrent — the
crawler pipeline rewrites fields at the same time a human may be
renaming a dataset or updating its `note`. Without a concurrency
control, two updates to the same row interleave under SQLAlchemy's
default "last write wins" semantics: whichever transaction commits
second silently overwrites the first.

Silent overwrite is the wrong failure mode for a metadata catalogue.
The user who loaded the page five seconds ago and clicked **Save**
expects the server to say "someone else changed this; reload and try
again", not to overwrite the concurrent edit they never saw.

We need a concurrency-control strategy that:

1. Detects stale writes at the **row** level, across the full entity
   surface (systems, datasets, data types, fields, …).
2. Does not block readers or serializers — the dominant traffic is
   reads.
3. Works symmetrically across HTTP API writes (through the service
   layer) and programmatic SDK writes.
4. Does not depend on database-specific locking primitives that would
   be expensive to replay if we introduced a second engine.

## 2. Options Considered

### Option A: Application-level optimistic locking via a `row_version` integer — **chosen**

- Every mutable entity has a `row_version: int` column, default `1`,
  server-side `server_default=text("1")` so legacy rows and hand
  inserts start at 1.
- Read responses include `row_version`; update requests must echo the
  value back.
- The service's `update` compares the payload's `row_version` to the
  database row's; mismatch raises `AppException(VERSION_CONFLICT)`
  (HTTP 409). Match increments the version and proceeds.
- The check lives in `GenericService.update` (ADR-002) so every entity
  that inherits the generic base gets it for free.

| Dimension | Assessment |
|-----------|------------|
| Correctness | **High** — last-write wins is replaced by last-write-only-if-stamp-matches |
| Reader impact | **None** — no locks are taken |
| Writer impact | **Minimal** — one extra column and one comparison per update |
| Portability | **Engine-independent** — plain integer column |
| Client integration | **Medium** — client must echo `row_version` in the update payload |

**Pros:**

- No row-level locks, no `SELECT ... FOR UPDATE`, no long-lived
  transactions — readers are unaffected.
- Conflict detection is explicit and visible at the API boundary: a
  409 with `VERSION_CONFLICT` is self-describing.
- Works for both REST and SDK clients without any protocol
  negotiation.
- The version integer doubles as a cheap change counter for audit
  purposes and cache invalidation.

**Cons:**

- Every client — UI, SDK, crawler — must read-then-write: keep the
  `row_version` it received, echo it back on update. The SDK does this
  automatically; hand-written curl calls must remember.
- Long-lived editor sessions see more conflicts than a human would
  intuitively expect (every unrelated server-side update bumps the
  version on the same row).
- Concurrent updates rebroadcast the same "modified by another user"
  message to both contending clients; there is no fine-grained
  "merge" resolution — conflict handling is reload-and-retry.

### Option B: Pessimistic locking via `SELECT ... FOR UPDATE`

Each service `update` opens a row lock before reading, holds it
through the mutation, and releases on commit.

**Pros:** conflicts are avoided, not detected.
**Cons:** readers and writers contend on the same lock queue; a slow
network between the request and commit hold locks longer than
necessary; async sessions and lock queues interact poorly; the whole
design becomes database-specific.

### Option C: Database-native row versioning (`xmin` / MVCC snapshot id)

PostgreSQL exposes each row's transaction id (`xmin`). Clients could
read it and include it in the `WHERE` clause of the `UPDATE`.

**Pros:** no extra column; uses existing MVCC metadata.
**Cons:** `xmin` is PG-specific; its wrap-around semantics are subtle;
exposing `xmin` to SDK clients ties them to PostgreSQL forever.

### Option D: Last-Modified / ETag-based HTTP conditional updates

Return `ETag` / `Last-Modified`, require `If-Match` / `If-Unmodified-
Since` on writes, translate the HTTP conditional into a DB predicate.

**Pros:** standard HTTP semantics.
**Cons:** the check lives at the HTTP layer, not at the service layer
— a non-HTTP caller (the crawler, a CLI) loses the guarantee unless
the service re-implements it; moving validation into middleware blurs
ADR-001's layer contracts.

### Option E: Event-sourced / CRDT

Model updates as events; resolve conflicts via convergent semantics.

**Pros:** no conflict dialog ever.
**Cons:** a massive architectural pivot for a problem that is solved
cheaply at row granularity; the metastore's primary record is the
current state, not the history.

## 3. Trade-off Analysis

Option B and C are engine-bound. Option D pushes concurrency control
into HTTP semantics, which diverges from ADR-001's service-layer
boundary. Option E is overkill. Option A keeps concurrency control
entirely in the service layer with a plain integer column, which
matches every other cross-entity concern we already solve generically
(see ADR-002).

## 4. Recommendation

Adopt Option A. Encode the `row_version` contract in mixins so both
the SQLAlchemy models and the Pydantic schemas are symmetric, and run
the compare-and-increment inside `GenericService.update` so every
entity inherits the behaviour by default.

## 5. Implementation Notes

### Database column — `VersionMixin`

[`backend/models/mixins.py`](../../backend/models/mixins.py):

```python
class VersionMixin:
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
    )
```

- `nullable=False` — a row always has a version.
- `default=1` — Python-side default for in-memory construction
  (tests, service-built objects).
- `server_default=text("1")` — database-side default so migrations
  that add the column to existing tables backfill every row with `1`
  without a separate update. Both defaults must agree; changing only
  one is a bug.

`VersionMixin` is included in both `MetaDataMixin` and
`SoftDeleteMetaDataMixin`, so every entity that carries the standard
audit columns automatically gets optimistic locking.

### Pydantic schemas — `VersionMixin` and `VersionedUpdateMixin`

[`schemas/aide_schemas/mixins.py`](../../schemas/aide_schemas/mixins.py):

```python
class VersionMixin(BaseModel):
    row_version: int          # used by Read schemas

class VersionedUpdateMixin(BaseModel):
    row_version: int          # used by Update schemas (required field)
```

- Read DTOs include `row_version` via `MetaDataMixin` — every
  `SystemRead`, `DatasetRead`, etc. already carries it.
- Update DTOs must inherit `VersionedUpdateMixin`, which makes
  `row_version` **required** on the wire. A client that omits it fails
  Pydantic validation at the edge with a 422 — they never reach the
  service's concurrency check.

### Service-layer compare-and-increment

[`backend/services/base.py`](../../backend/services/base.py) —
`GenericService.update`:

```python
update_data = obj_in.model_dump(exclude_unset=True)
client_row_version = update_data.pop("row_version", None)

async with uow:
    db_obj = await repo.get(obj_id)
    if not db_obj:
        raise AppException(self.not_found_error_code)

    if client_row_version is not None and hasattr(db_obj, "row_version"):
        if db_obj.row_version != client_row_version:
            raise AppException(VERSION_CONFLICT)

    await self._pre_update(uow, db_obj, obj_in, updater_id)

    for field, value in update_data.items():
        setattr(db_obj, field, value)

    if hasattr(db_obj, "row_version"):
        db_obj.row_version += 1
```

Key points:

- `row_version` is **popped** from `update_data` before the generic
  "apply every remaining field to the ORM object" loop. The service
  controls the increment; clients never set the version directly.
- The `client_row_version is not None` guard preserves the base-class
  behaviour for entities that do not carry `VersionMixin` (currently
  all entities do, but the guard keeps the generic safe).
- The increment happens after `_pre_update` runs, so a validation
  failure in the hook leaves the row untouched (the transaction rolls
  back via UoW — ADR-003).
- The error code `VERSION_CONFLICT` is registered in
  [`backend/core/errors.py`](../../backend/core/errors.py) at HTTP
  status `409 CONFLICT` (ADR-005).

### Polymorphic entities

`DatasetService.update` (ADR-008) does not inherit
`GenericService.update` — it has its own override because it must
dispatch on the `kind` discriminator. The override reproduces the same
compare-and-increment logic verbatim
([`backend/services/dataset.py:150-172`](../../backend/services/dataset.py)).
If the base-class logic changes, the dataset copy must be kept in
sync. This duplication is small and deliberate; factoring the check
into a shared helper would be a net loss in readability for one
override.

### Batch writes (`create_many`)

Batch inserts do not go through `update`, so `row_version` simply
uses the server default (`1`). There is no conflict detection on
create — the primary-key uniqueness constraint is the only guard,
which is appropriate: there is no "previous version" to conflict
against.

### Client contract

HTTP clients must:

1. `GET /api/v1/<entity>/{id}` and keep the `row_version` from the
   response.
2. Include that `row_version` in the `PATCH` / `PUT` payload along
   with the changed fields.
3. On `409 VERSION_CONFLICT`, re-read the entity and merge or retry
   with the fresh `row_version`. The response body contains the
   canonical `error_code` for branching (ADR-005).

The SDK (`aide-sdk`) already threads `row_version` through its update
methods; hand-written callers must do the same.

### Testing

- Service unit tests (ADR-007) construct an ORM object with a chosen
  `row_version`, then call `update` with a mismatched value and assert
  `AppException.error_code == VERSION_CONFLICT`.
- API tests do the full round-trip: read, mutate the version client-
  side, send — expect `409`.
- Repository tests do **not** need to exercise `row_version` — the
  contract is enforced in the service layer, not the repository.

### What not to do

- Do not set `row_version` manually from a service hook or from an API
  handler. Only `GenericService.update` and the polymorphic
  `DatasetService.update` own the increment.
- Do not expose an endpoint that lets a client choose the next
  version. Versions are opaque tokens — clients compare-and-submit,
  they do not compute.
- Do not skip the check by `exclude={"row_version"}` on an update
  schema. Required-ness is the enforcement mechanism; any update
  schema must inherit `VersionedUpdateMixin`.
- Do not swap the integer for a timestamp. Sub-second concurrent
  updates in the same request can produce identical timestamps;
  integer monotonicity with `+1` is unambiguous.

## 6. Consequences

- **Easier:** every entity gets conflict detection for free as soon
  as it carries `VersionMixin`; 409 responses are uniform and self-
  describing; the SDK's concurrency story is one sentence.
- **Harder:** long-lived editor workflows see more conflicts than an
  HTML form with a 10-minute session expects; clients that forget to
  echo `row_version` fail fast (good) but the fix is not always
  obvious to a first-time integrator.
- **Revisit when:** we need a domain-level "merge" story for specific
  fields (e.g. additive tag changes should not conflict with a rename)
  — at that point, per-field versioning or a CRDT substructure may be
  worth the complexity, but not before.
