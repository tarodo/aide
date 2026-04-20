# ADR-002: Generic Base Classes — `BaseRepository[M]` and `GenericService[M, C, U, R]`

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

ADR-001 fixes the layer structure. Within those layers, nearly every entity
needs the same shape of code: paginated list, get by id, create, update with
optimistic-lock check, delete, and (for some) soft-delete + restore.

AIDE already has 15+ entities. Copy-pasting ~200 lines of repository and
service boilerplate into each one would:

- Multiply drift: a subtle bug fixed in one entity does not propagate.
- Make pagination, filtering, and slow-query logging inconsistent across
  entities.
- Bury the genuinely entity-specific logic (the validation hooks) under a
  wall of identical code.

We need a contract that factors out the boilerplate and lets each entity's
files focus on **what is different**, not what is the same.

## 2. Options Considered

### Option A: Generic base classes with `TypeVar` — **chosen**

Two generic bases, one per layer:

- `BaseRepository[ModelType]` — CRUD, pagination, filter/sort, slow-query
  logging. `SoftDeleteRepository[ModelType]` extends it for entities that
  carry `deleted_at`.
- `GenericService[ModelType, CreateSchemaType, UpdateSchemaType,
  ReadSchemaType]` — orchestrates one method per CRUD action, wires the
  UoW, and calls entity-specific `_pre_*` validation hooks.
  `SoftDeleteService[...]` extends it with soft-delete + restore.

Each subclass sets its `model` class attr (repository) or passes the
model, repository class, read schema, and not-found error code to
`super().__init__` (service), then overrides only the hooks it needs.

| Dimension | Assessment |
|-----------|------------|
| Boilerplate per entity | **Low** — ~20 lines of service, ~0–30 of repo depending on custom queries |
| Type safety | **High** — `TypeVar` bounds propagate return types to callers |
| Learning curve | **Medium** — contributors must read the base classes once |
| Runtime cost | **None** — generics are erased; no metaclass magic |
| Consistency | **High** — every entity pages, filters, logs the same way |

**Pros:**

- A bug fix in the base (e.g. slow-query threshold, `row_version` handling)
  reaches every entity for free.
- Pagination, filter DSL, and sort DSL are implemented once.
- Hook seams (`_pre_create`, `_pre_update`, `_pre_delete`) give a clear
  place for cross-entity validation without reopening the CRUD code.
- Python generics + `TypeVar` give `mypy` enough to catch wrong-schema
  returns at static-check time.

**Cons:**

- Base classes accumulate responsibilities over time — they must be kept
  lean and single-purpose.
- `cast(SpecificRepository, self._get_repository(...))` is needed when a
  service reaches for custom repo methods, because the generic bound is
  `BaseRepository[ModelType]`.
- Multi-generic signatures (`[M, C, U, R]`) can be intimidating to first-
  time readers.

### Option B: Copy-paste CRUD per entity

Each entity owns a full CRUD implementation, with helpers shared via plain
functions but no class hierarchy.

**Pros:** zero indirection; each entity is self-contained and fully
readable top-to-bottom.
**Cons:** pagination / filter / sort diverge; a fix must be applied 15+
times; consistency is a review-process problem instead of a compile-time
one.

### Option C: Third-party generic CRUD library (e.g. `fastapi-crud`, `SQLModel`-style)

Adopt an external framework that generates CRUD routers + services from
the model.

**Pros:** less in-house code to maintain.
**Cons:** bound to the framework's opinions; hooks for custom validation
are often leaky; the project already has enough entity-specific logic
(`_pre_delete` dependent-entity checks, `row_version`, soft-delete) that
the framework's escape hatches become the hot path — at which point the
framework is a cost, not a benefit.

## 3. Trade-off Analysis

Option B wins on "first entity readability" and loses on "tenth entity
consistency". Option C wins on "day one velocity" and loses the moment
requirements exceed the library's hooks — and our `_pre_delete` dependent-
entity guards already exceed typical CRUD-library hooks.

Option A pays a one-time cost (read the bases) and delivers a repeatable
shape thereafter, which matches our growth trajectory.

## 4. Recommendation

Adopt Option A. Treat the base classes as an internal contract — changes
to them are schema-like changes and require review.

## 5. Implementation Notes

### Repository bases

`BaseRepository[ModelType]` lives in
[`backend/repositories/base.py`](../../backend/repositories/base.py). Every
entity repository subclasses it (or its soft-delete variant) and sets the
`model` class attribute:

```python
class SystemRepository(SoftDeleteRepository[System]):
    model = System

    async def get_by_code(self, code: str) -> System | None:
        ...
```

Provided by the base:

| Method | Purpose |
|--------|---------|
| `get(obj_id)` | Fetch by primary key; soft-delete variant filters out deleted rows |
| `get_multi(skip, limit)` | Unfiltered list with offset + limit |
| `get_multi_paginated(skip, limit, filters, sort, include_deleted)` | Page + filter + sort; returns `(items, total)` |
| `create(obj_in)` | Add + flush + refresh |
| `create_many(objs)` | `add_all` + flush (batch insert) |
| `update(db_obj)` | Add + flush + refresh |
| `delete(db_obj)` | Hard delete via `session.delete`; soft-delete variant sets `deleted_at = func.now()` |
| `restore(db_obj)` | Soft-delete only — clears `deleted_at` and `deleted_by` |
| `get_including_deleted(obj_id)` | Soft-delete only — bypasses the default filter |
| `_execute(stmt, method=...)` | Wrapper around `session.execute` that logs slow queries |
| `_apply_filters(query, filters)` | Applies the shared `FilterSpec` DSL |
| `_apply_sort(query, sort)` | Applies `[(field, desc_bool), ...]` sort spec |

When adding a custom query helper, use `self._execute` (not raw
`self.session.execute`) so the helper participates in slow-query logging.

### Service bases

`GenericService[ModelType, CreateSchemaType, UpdateSchemaType,
ReadSchemaType]` lives in
[`backend/services/base.py`](../../backend/services/base.py). Every entity
service subclasses it (or its soft-delete variant):

```python
class SystemService(SoftDeleteService[System, SystemCreate, SystemUpdate, SystemRead]):
    def __init__(self):
        super().__init__(
            model=System,
            repository=SystemRepository,
            read_schema=SystemRead,
            not_found_error_code=errors.SYSTEM_NOT_FOUND,
        )
```

The four generic parameters (in order):

1. `ModelType` — the SQLAlchemy model class.
2. `CreateSchemaType` — Pydantic schema accepted by `POST`.
3. `UpdateSchemaType` — Pydantic schema accepted by `PATCH` / `PUT`.
4. `ReadSchemaType` — Pydantic schema returned to clients.

The constructor takes four concrete values:

- `model` — the ORM class (mirrors `ModelType`).
- `repository` — the repository **class**, not an instance. The base
  instantiates it per request with the current session.
- `read_schema` — used to produce `ReadSchemaType` from the ORM object.
- `not_found_error_code` — an error-code string from `backend.core.errors`
  raised as `AppException(code)` when a lookup misses (see ADR-005).

Provided methods: `get_by_id`, `get_paginated`, `create`, `create_many`,
`update`, `delete`. `SoftDeleteService` additionally provides `restore`
and overrides `delete` with the soft-delete path.

### Hook contract

Subclasses override these hooks for entity-specific validation; they run
**inside** the `async with uow:` block, so they may call
`self._get_repository(uow.session)`, reach into `uow.<other_repo>`, or
issue ad-hoc `uow.session.execute(...)` queries.

| Hook | When it runs | Typical use |
|------|--------------|-------------|
| `_pre_create(uow, obj_in, creator_id)` | Before the model is constructed and inserted | Check uniqueness, verify FK targets exist |
| `_pre_update(uow, db_obj, obj_in, updater_id)` | After `get(obj_id)`, before field assignment and flush | Re-check uniqueness on renamed `code`, verify new FK targets |
| `_pre_delete(uow, db_obj)` *(soft-delete only)* | Before `deleted_at` is set | Refuse delete if dependent children exist |

Hooks **must** raise `AppException(error_code)` on failure; they must not
raise `HTTPException` or return a result.

### Accessing a custom repository method

The generic `_get_repository` returns `BaseRepository[ModelType]`, which
does not expose entity-specific helpers like `get_by_code`. When a hook
needs one, cast:

```python
repo = cast(SystemRepository, self._get_repository(uow.session))
if await repo.get_by_code(obj_in.code):
    raise AppException(errors.SYSTEM_ALREADY_EXISTS)
```

`cast` is a mypy-only annotation; it has no runtime cost. Do not reach
into `self.repository` directly — it is a class, not an instance bound to
the request's session.

### `row_version` handling in the base

`GenericService.update` consumes `row_version` from the update schema if
present, compares it to `db_obj.row_version`, raises
`AppException(VERSION_CONFLICT)` on mismatch, then increments the value
after the hook runs. Entity services do not need to re-implement this —
see ADR-010 for the optimistic-locking decision.

## 6. Consequences

- **Easier:** new entity = 1 repository file + 1 service file + overrides
  only for the validation that is genuinely entity-specific. Bug fixes in
  pagination / filtering / slow-query logging propagate on merge.
- **Harder:** changes to the base classes touch every entity implicitly.
  Review such changes carefully and treat the base class as a stable
  contract; run the full test suite (`make test-docker`) before merging.
- **Revisit when:** we find ourselves defeating the generic bound with
  `cast` in every service method (signal that the contract is too narrow),
  or when a second persistence engine appears that needs its own
  repository hierarchy.
