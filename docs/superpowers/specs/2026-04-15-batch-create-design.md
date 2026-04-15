# Batch Create — Design Spec

**Date:** 2026-04-15
**Status:** Approved (brainstorming)
**Scope:** backend + sdk + crawler

## Problem

Crawler hot path in `crawler/aide_crawler/applier.py` issues one `POST` per field, per type-instance node, and per field binding. A dataset with 200 fields and an average of 1.5 type-instance nodes per field produces ~700 round-trips. Latency and connection overhead dominate runtime.

## Goals

- Generic batch-create endpoint available on all POST-creatable resources.
- SDK surfaces a uniform `create_many(...)` on every resource.
- Crawler applier uses batch calls for fields, type instances, and field bindings.
- Future entities inherit batch support for free when they extend `GenericService` and the router helper.

## Non-goals (YAGNI)

- Batch update, batch delete.
- Idempotency keys.
- Async / queued batches.
- Partial-success semantics.
- Batch support for resources not currently needed (systems, datasets, schemas, etc.) — wiring is one line each when needed later.

## Design

### Semantics

- **All-or-nothing.** One UoW transaction per batch request. Any error (validation, FK, unique) rolls the entire batch back.
- **Order preserved.** Response items are in the same order as the request.
- **Max batch size:** 500 items per request (configurable via `settings.MAX_BATCH_SIZE`). Exceeding → HTTP 422.
- **Empty batch:** HTTP 422.

### Backend

#### `GenericService.create_many`

New method on `backend/services/base.py`:

```python
async def create_many(
    self,
    uow: UnitOfWork,
    items: list[CreateSchemaType],
    creator_id: uuid.UUID | None = None,
) -> list[ReadSchemaType]:
```

Behavior:

- Opens single UoW.
- For each item: calls existing `_pre_create` hook, constructs `self.model(**item.model_dump())`, sets `created_by`/`updated_by` if applicable.
- Calls `repo.create_many(db_objs)`.
- Returns `[read_schema.model_validate(o) for o in created]` in input order.
- Logs one `entity.batch_created` event with `count` and `entity`.

#### `BaseRepository.create_many`

New method on `backend/repositories/base.py`:

```python
async def create_many(self, objs: list[ModelType]) -> list[ModelType]:
    self.session.add_all(objs)
    await self.session.flush()
    return objs
```

One round-trip flush. Server-generated fields (ids, timestamps, row_version) populated via RETURNING per SQLAlchemy defaults.

#### Schemas

New file `schemas/aide_schemas/batch.py`:

```python
from typing import Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)

class BatchCreateRequest(BaseModel, Generic[T]):
    items: list[T] = Field(min_length=1)

class BatchCreateResponse(BaseModel, Generic[T]):
    items: list[T]
    count: int
```

Re-exported from `backend/schemas/batch.py`.

#### Router helper

New file `backend/api/v1/utils/batch.py`:

```python
def register_batch_create(
    router: APIRouter,
    *,
    service: GenericService,
    create_schema: Type[BaseModel],
    read_schema: Type[BaseModel],
    path: str = "/batch",
) -> None:
    ...
```

Registers `POST {path}` that:

1. Parses `BatchCreateRequest[CreateSchema]`.
2. Enforces `len(items) <= settings.MAX_BATCH_SIZE` (422 otherwise).
3. Delegates to `service.create_many(uow, items, creator_id)`.
4. Returns `BatchCreateResponse[ReadSchema]`.

#### Wired endpoints (phase 1)

- `POST /api/v1/fields/batch`
- `POST /api/v1/type-instances/batch`
- `POST /api/v1/field-bindings/batch`
- `POST /api/v1/data-types/batch`

Existing single-create endpoints unchanged.

#### Config

Add to `backend/core/config.py` Settings:

```python
MAX_BATCH_SIZE: int = 500
```

### SDK

#### `BaseResource.create_many`

New method on `sdk/aide_sdk/resources/base.py`:

```python
async def create_many(
    self,
    items: list[CreateT],
    *,
    chunk_size: int = 500,
) -> list[ReadT]:
```

Behavior:

- If `items` empty → return `[]`, no HTTP call.
- Chunks `items` into slices of `chunk_size`.
- For each chunk: `POST {_path}/batch` with `{"items": [...]}` body, parses `BatchCreateResponse[ReadT]`, extends result list.
- Returns flat `list[ReadT]`.
- On exception mid-loop: prior chunks already committed server-side; exception propagates unchanged. Documented in docstring.

Default `chunk_size` matches server default (500). Overridable per call.

Available on all resources automatically via inheritance.

### Crawler

Refactor `crawler/aide_crawler/applier.py`:

#### Phase: apply-dataset

For each dataset after schema-v1 resolution:

1. **Fields batch**
   - Diff existing `{name: id}` map vs normalized fields.
   - Build `list[FieldCreate]` for missing.
   - `await client.fields.create_many(to_create)`.
   - Merge responses into the name→id map.

2. **Type-instance tree batch (topological by depth)**
   - Flatten per-field `TypeNode` trees into records: `(field_id, path, depth, node, parent_path)`.
   - Group by `depth` ascending.
   - For each depth level:
     - Build `list[TypeInstanceCreate]` with `parent_id` resolved from prior level's `{path: id}` map. For depth 0, `parent_id=None`.
     - `await client.type_instances.create_many(level_items)`.
     - Record `{path: id}` for children of the next level to reference.
   - After all levels: map `{field_id: root_type_instance_id}` (depth-0 roots).

3. **Field bindings batch**
   - Diff existing `{field_id}` set on schema vs desired.
   - Build `list[FieldBindingCreate]`.
   - `await client.field_bindings.create_many(bindings)`.

Unchanged:

- Schema find-or-create (single call, v1 only).
- Type cache population.
- Existing-entity paginated listing.
- `data_types` in crawler path (type cache already batches implicitly via list).

Expected reduction: ~700 POSTs → ~3–5 batch calls per dataset.

## Testing

### Backend (`tests/api/` + `tests/services/`)

Parametrized helper across the 4 wired resources:

- `test_<resource>_batch_create_ok` — 3 items → 200, envelope shape, rows persisted.
- `test_<resource>_batch_all_or_nothing` — inject one FK-violating item → 4xx, **zero** rows in DB.
- `test_<resource>_batch_exceeds_limit` — 501 items → 422.
- `test_<resource>_batch_empty` — `{items: []}` → 422.
- `test_<resource>_batch_sets_creator_id` — assert `created_by`/`updated_by` populated.

### SDK (`sdk/tests/`)

- `test_create_many_empty` — no HTTP calls, returns `[]`.
- `test_create_many_single_chunk` — 3 items → 1 HTTP call, envelope parsed.
- `test_create_many_chunks` — 1200 items + `chunk_size=500` → 3 HTTP calls, flat list of 1200.
- `test_create_many_mid_chunk_failure` — second chunk raises → exception propagates, partial results NOT returned (caller sees raised error).

### Crawler (`crawler/tests/`)

- Update applier tests to assert batch endpoints invoked (not per-item).
- Topological-batch test: dataset with nested types (depth 2) → one batch call per depth level in correct order, parent_ids resolved.
- Existing differ / normalizer tests unchanged.

## Migrations

None. No schema changes.

## Rollout

1. Backend: schemas + repo + service + router helper + wire 4 endpoints + tests.
2. SDK: `BaseResource.create_many` + tests. Bump SDK version.
3. Crawler: refactor applier + update tests.
4. Manual end-to-end against `manual_test/` fixture.

Each step ships as a separate commit; the three packages are independent after backend lands.
