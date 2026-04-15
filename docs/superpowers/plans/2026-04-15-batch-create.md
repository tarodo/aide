# Batch Create Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add generic all-or-nothing batch-create support to backend (`GenericService` + router helper), SDK (`BaseResource.create_many`), and refactor crawler applier to use batching.

**Architecture:** A single new `create_many` method on `GenericService` and `BaseRepository` uses one UoW transaction per batch. The existing `create_crud_router` helper gains a `supports_batch=True` flag that registers `POST /batch` accepting `{items: [...]}` and returning `{items: [...], count: N}`. The SDK mirrors this with `BaseResource.create_many` that auto-chunks. Crawler applier refactors per-field/per-node/per-binding loops into three topologically-ordered batch calls per dataset.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, httpx, pytest/pytest-asyncio. Packages wired via `[tool.uv.sources]`.

**Spec:** `docs/superpowers/specs/2026-04-15-batch-create-design.md`

---

## File Structure

**New files:**
- `schemas/aide_schemas/batch.py` — generic `BatchCreateRequest[T]`, `BatchCreateResponse[T]`
- `backend/schemas/batch.py` — re-export
- `tests/api/test_batch.py` — parametrized batch endpoint tests
- `tests/services/test_generic_service_batch.py` — service-level unit test
- `sdk/tests/test_create_many.py` — SDK chunking + empty/propagation tests

**Modified files:**
- `backend/core/settings.py` — add `MAX_BATCH_SIZE: int = 500`
- `backend/repositories/base.py` — add `create_many`
- `backend/services/base.py` — add `create_many`
- `backend/api/v1/utils/crud_router.py` — add `supports_batch` flag → registers `POST /batch`
- `backend/api/v1/fields.py` — pass `supports_batch=True`
- `backend/api/v1/type_instances.py` — pass `supports_batch=True`
- `backend/api/v1/field_bindings.py` — pass `supports_batch=True`
- `backend/api/v1/data_types.py` — pass `supports_batch=True`
- `sdk/aide_sdk/resources/base.py` — add `create_many`
- `crawler/aide_crawler/applier.py` — refactor loops into batched calls
- `crawler/tests/test_applier.py` — update assertions

---

## Task 1: Batch Schemas

**Files:**
- Create: `schemas/aide_schemas/batch.py`
- Create: `backend/schemas/batch.py`
- Test: `tests/services/test_generic_service_batch.py` (schema import smoke)

- [ ] **Step 1: Write schema definition**

Create `schemas/aide_schemas/batch.py`:

```python
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class BatchCreateRequest(BaseModel, Generic[T]):
    """Request body for batch-create endpoints."""

    items: list[T] = Field(min_length=1)


class BatchCreateResponse(BaseModel, Generic[T]):
    """Response envelope for batch-create endpoints."""

    items: list[T]
    count: int
```

- [ ] **Step 2: Re-export from backend schemas**

Create `backend/schemas/batch.py`:

```python
from aide_schemas.batch import BatchCreateRequest, BatchCreateResponse

__all__ = ["BatchCreateRequest", "BatchCreateResponse"]
```

- [ ] **Step 3: Write schema smoke test**

Create `tests/services/test_generic_service_batch.py`:

```python
from pydantic import BaseModel

from backend.schemas.batch import BatchCreateRequest, BatchCreateResponse


class _Item(BaseModel):
    name: str


def test_batch_request_requires_nonempty_items():
    from pydantic import ValidationError
    import pytest

    BatchCreateRequest[_Item].model_validate({"items": [{"name": "a"}]})

    with pytest.raises(ValidationError):
        BatchCreateRequest[_Item].model_validate({"items": []})


def test_batch_response_shape():
    resp = BatchCreateResponse[_Item].model_validate(
        {"items": [{"name": "a"}, {"name": "b"}], "count": 2}
    )
    assert resp.count == 2
    assert [i.name for i in resp.items] == ["a", "b"]
```

- [ ] **Step 4: Run test**

Run: `make test-docker` (or inside container: `pytest tests/services/test_generic_service_batch.py -v`)
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add schemas/aide_schemas/batch.py backend/schemas/batch.py tests/services/test_generic_service_batch.py
git commit -m "feat(schemas): add generic batch create request/response"
```

---

## Task 2: Settings — MAX_BATCH_SIZE

**Files:**
- Modify: `backend/core/settings.py`

- [ ] **Step 1: Add setting**

Edit `backend/core/settings.py`, inside the `Settings` class (after `SLOW_QUERY_THRESHOLD_MS`):

```python
    MAX_BATCH_SIZE: int = 500
```

- [ ] **Step 2: Confirm import works**

Run: `uv run python -c "from backend.core.settings import settings; print(settings.MAX_BATCH_SIZE)"`
Expected: prints `500`.

- [ ] **Step 3: Commit**

```bash
git add backend/core/settings.py
git commit -m "feat(config): add MAX_BATCH_SIZE setting (default 500)"
```

---

## Task 3: Repository `create_many`

**Files:**
- Modify: `backend/repositories/base.py`
- Test: `tests/repositories/test_base_batch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/repositories/test_base_batch.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SystemKind
from backend.repositories.system_kind import SystemKindRepository


@pytest.mark.asyncio
async def test_create_many_persists_all(transactional_session: AsyncSession):
    repo = SystemKindRepository(transactional_session)
    objs = [
        SystemKind(code=f"BATCH_{i}", name=f"Batch {i}") for i in range(3)
    ]
    created = await repo.create_many(objs=objs)
    assert len(created) == 3
    for obj in created:
        assert obj.id is not None
    # Order preserved
    assert [o.code for o in created] == ["BATCH_0", "BATCH_1", "BATCH_2"]


@pytest.mark.asyncio
async def test_create_many_empty_returns_empty(transactional_session: AsyncSession):
    repo = SystemKindRepository(transactional_session)
    created = await repo.create_many(objs=[])
    assert created == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test-docker`
Expected: FAIL — `BaseRepository` has no `create_many`.

- [ ] **Step 3: Implement `create_many`**

Edit `backend/repositories/base.py`. Add method inside `BaseRepository`, after `create`:

```python
    async def create_many(self, *, objs: list[ModelType]) -> list[ModelType]:
        if not objs:
            return []
        self.session.add_all(objs)
        await self.session.flush()
        return objs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `make test-docker`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/repositories/base.py tests/repositories/test_base_batch.py
git commit -m "feat(repo): add BaseRepository.create_many"
```

---

## Task 4: Service `create_many`

**Files:**
- Modify: `backend/services/base.py`
- Modify: `tests/services/test_generic_service_batch.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/services/test_generic_service_batch.py`:

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.uow import UnitOfWork
from backend.models import SystemKind
from backend.services.system_kind import SystemKindService


@pytest.mark.asyncio
async def test_service_create_many_all_or_nothing(
    transactional_session: AsyncSession,
):
    uow = UnitOfWork(session_factory=lambda: transactional_session)
    service = SystemKindService()

    items = [
        _kind_create("OK_A"),
        _kind_create("OK_B"),
    ]
    created = await service.create_many(uow=uow, items=items)
    assert len(created) == 2
    assert [c.code for c in created] == ["OK_A", "OK_B"]


def _kind_create(code: str):
    from backend.schemas.system_kind import SystemKindCreate

    return SystemKindCreate(code=code, name=f"Name {code}")


@pytest.mark.asyncio
async def test_service_create_many_rollback_on_error(
    transactional_session: AsyncSession,
):
    """Any failure inside the batch rolls back all rows."""
    uow = UnitOfWork(session_factory=lambda: transactional_session)
    service = SystemKindService()

    # Seed one existing row to make the second item's unique code collide.
    await service.create_many(
        uow=uow, items=[_kind_create("DUP_X")]
    )

    items = [
        _kind_create("FRESH_A"),
        _kind_create("DUP_X"),  # unique violation
    ]
    with pytest.raises(Exception):
        await service.create_many(uow=uow, items=items)

    # FRESH_A must not have been committed.
    from sqlalchemy import select

    rows = (
        await transactional_session.execute(
            select(SystemKind).where(SystemKind.code == "FRESH_A")
        )
    ).scalars().all()
    assert rows == []
```

> Note: if `UnitOfWork` signature differs, follow the existing pattern in `tests/services/test_system_kind_service.py`. Use whichever UoW construction that test file uses.

- [ ] **Step 2: Run test**

Run: `make test-docker -- -k test_service_create_many`
Expected: FAIL — `create_many` not defined on `GenericService`.

- [ ] **Step 3: Implement `create_many`**

Edit `backend/services/base.py`. Add method inside `GenericService`, after `create`:

```python
    async def create_many(
        self,
        uow: UnitOfWork,
        items: list[CreateSchemaType],
        creator_id: uuid.UUID | None = None,
    ) -> list[ReadSchemaType]:
        """Create many objects in a single transaction (all-or-nothing)."""
        if not items:
            return []

        async with uow:
            repo: BaseRepository[ModelType] = self._get_repository(uow.session)

            db_objs: list[ModelType] = []
            for obj_in in items:
                await self._pre_create(uow, obj_in, creator_id)
                db_obj = self.model(**obj_in.model_dump())
                if creator_id and hasattr(db_obj, "created_by"):
                    setattr(db_obj, "created_by", creator_id)
                    setattr(db_obj, "updated_by", creator_id)
                db_objs.append(db_obj)

            created = await repo.create_many(objs=db_objs)
            logger.info(
                "entity.batch_created",
                entity=self._entity_name,
                count=len(created),
                user_id=str(creator_id) if creator_id else None,
            )
            return [self.read_schema.model_validate(o) for o in created]
```

- [ ] **Step 4: Run tests**

Run: `make test-docker -- -k test_service_create_many`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/base.py tests/services/test_generic_service_batch.py
git commit -m "feat(service): add GenericService.create_many with all-or-nothing tx"
```

---

## Task 5: Router — `supports_batch` flag

**Files:**
- Modify: `backend/api/v1/utils/crud_router.py`

- [ ] **Step 1: Add imports + flag**

Edit `backend/api/v1/utils/crud_router.py`. Add near the top imports:

```python
from backend.core.settings import settings
from backend.schemas.batch import BatchCreateRequest, BatchCreateResponse
```

Add parameter to `create_crud_router` signature (after `default_sort`):

```python
    supports_batch: bool = False,
    batch_create_dependencies: Sequence[Any] | None = None,
```

Inside the function body, right after the existing `create` route (after line ~165), add:

```python
    if supports_batch:
        _batch_deps = (
            batch_create_dependencies
            if batch_create_dependencies is not None
            else create_dependencies
        )

        @router.post(
            "/batch",
            response_model=BatchCreateResponse[read_schema],  # type: ignore[valid-type]
            status_code=status.HTTP_201_CREATED,
            summary=f"Batch-create {entity_name}s (all-or-nothing)",
            dependencies=_batch_deps,
            responses={
                **build_error_responses(
                    *(create_error_codes or []), UNAUTHORIZED, FORBIDDEN
                ),
            },
        )
        async def create_batch(
            payload: BatchCreateRequest[create_schema],  # type: ignore[valid-type]
            service: ServiceType = Depends(service_dependency),
            uow: UnitOfWork = Depends(UnitOfWork),
            current_user: User = Depends(get_current_user),
        ) -> Any:
            if len(payload.items) > settings.MAX_BATCH_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Batch too large: {len(payload.items)} items; "
                        f"max is {settings.MAX_BATCH_SIZE}"
                    ),
                )
            created = await service.create_many(
                uow=uow, items=payload.items, creator_id=current_user.id
            )
            return BatchCreateResponse(items=created, count=len(created))
```

- [ ] **Step 2: Confirm nothing breaks for existing routers**

Run: `make check && make test-docker -- -k "fields or type_instances or field_bindings or data_types"`
Expected: existing tests still PASS (flag defaults to False, no behavior change).

- [ ] **Step 3: Commit**

```bash
git add backend/api/v1/utils/crud_router.py
git commit -m "feat(api): add supports_batch flag to create_crud_router"
```

---

## Task 6: Wire batch on fields, type_instances, field_bindings, data_types

**Files:**
- Modify: `backend/api/v1/fields.py`
- Modify: `backend/api/v1/type_instances.py`
- Modify: `backend/api/v1/field_bindings.py`
- Modify: `backend/api/v1/data_types.py`

- [ ] **Step 1: Enable flag in each router**

In each of the four files, find the `create_crud_router(...)` call and add `supports_batch=True,` as a new kwarg:

```python
crud_router = create_crud_router(
    # ... existing args ...
    supports_batch=True,
)
```

- [ ] **Step 2: Sanity-check routes are registered**

Run: `uv run python -c "from backend.main import app; print([r.path for r in app.routes if '/batch' in r.path])"`
Expected: four paths printed, e.g.:
```
['/api/v1/fields/batch', '/api/v1/type-instances/batch', '/api/v1/field-bindings/batch', '/api/v1/data-types/batch']
```

(Exact prefixes depend on how each router is mounted in `main.py` — verify they appear.)

- [ ] **Step 3: Commit**

```bash
git add backend/api/v1/fields.py backend/api/v1/type_instances.py \
        backend/api/v1/field_bindings.py backend/api/v1/data_types.py
git commit -m "feat(api): enable batch create for fields, type_instances, field_bindings, data_types"
```

---

## Task 7: Integration tests for batch endpoints

**Files:**
- Create: `tests/api/test_batch.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_batch.py`. Model it on the fixture setup used in `tests/api/test_fields.py` (superuser fixture, auth headers, supporting entities). Use the existing `superuser_token_headers`, `test_system`, `test_dataset` fixtures; if they are function-scoped in the other file, duplicate them here (do not import private fixtures across files unless they are in `conftest.py`).

Minimum test body (pick `fields` for the deep test — it covers creator_id, FK, etc.):

```python
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import (
    Dataset,
    DatasetRdbms,
    Field,
    System,
    SystemFlavor,
    SystemKind,
    User,
)


# Reuse fixture shapes from tests/api/test_fields.py:
# superuser, superuser_token_headers, test_system, test_dataset.
# Copy them verbatim from that file.


@pytest.mark.asyncio
async def test_fields_batch_create_ok(
    async_client: AsyncClient,
    superuser_token_headers: dict[str, str],
    test_dataset: Dataset,
    transactional_session: AsyncSession,
):
    payload = {
        "items": [
            {
                "dataset_id": str(test_dataset.id),
                "name": f"col_{i}",
                "ordinal": i,
            }
            for i in range(3)
        ]
    }
    resp = await async_client.post(
        "/api/v1/fields/batch",
        json=payload,
        headers=superuser_token_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["count"] == 3
    assert len(body["items"]) == 3
    assert [i["name"] for i in body["items"]] == ["col_0", "col_1", "col_2"]
    for item in body["items"]:
        assert item["created_by"] is not None

    rows = (
        await transactional_session.execute(
            select(Field).where(Field.dataset_id == test_dataset.id)
        )
    ).scalars().all()
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_fields_batch_all_or_nothing(
    async_client: AsyncClient,
    superuser_token_headers: dict[str, str],
    test_dataset: Dataset,
    transactional_session: AsyncSession,
):
    # Seed one row; the second item in the batch will collide on (dataset_id, name).
    payload_seed = {
        "items": [
            {
                "dataset_id": str(test_dataset.id),
                "name": "dup_col",
                "ordinal": 0,
            }
        ]
    }
    await async_client.post(
        "/api/v1/fields/batch", json=payload_seed, headers=superuser_token_headers
    )

    payload = {
        "items": [
            {
                "dataset_id": str(test_dataset.id),
                "name": "fresh_col",
                "ordinal": 1,
            },
            {
                "dataset_id": str(test_dataset.id),
                "name": "dup_col",
                "ordinal": 2,
            },
        ]
    }
    resp = await async_client.post(
        "/api/v1/fields/batch",
        json=payload,
        headers=superuser_token_headers,
    )
    assert resp.status_code >= 400

    rows = (
        await transactional_session.execute(
            select(Field).where(
                Field.dataset_id == test_dataset.id,
                Field.name == "fresh_col",
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_fields_batch_too_large(
    async_client: AsyncClient,
    superuser_token_headers: dict[str, str],
    test_dataset: Dataset,
    monkeypatch,
):
    from backend.core.settings import settings

    monkeypatch.setattr(settings, "MAX_BATCH_SIZE", 2)
    payload = {
        "items": [
            {"dataset_id": str(test_dataset.id), "name": f"c_{i}", "ordinal": i}
            for i in range(3)
        ]
    }
    resp = await async_client.post(
        "/api/v1/fields/batch",
        json=payload,
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fields_batch_empty_rejected(
    async_client: AsyncClient,
    superuser_token_headers: dict[str, str],
):
    resp = await async_client.post(
        "/api/v1/fields/batch",
        json={"items": []},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_field_bindings_batch_endpoint_registered(
    async_client: AsyncClient, superuser_token_headers: dict[str, str]
):
    # Smoke: route exists and rejects empty payload with 422 (not 404).
    resp = await async_client.post(
        "/api/v1/field-bindings/batch",
        json={"items": []},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_type_instances_batch_endpoint_registered(
    async_client: AsyncClient, superuser_token_headers: dict[str, str]
):
    resp = await async_client.post(
        "/api/v1/type-instances/batch",
        json={"items": []},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_data_types_batch_endpoint_registered(
    async_client: AsyncClient, superuser_token_headers: dict[str, str]
):
    resp = await async_client.post(
        "/api/v1/data-types/batch",
        json={"items": []},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422
```

> Before running, copy the exact fixtures (`superuser`, `superuser_token_headers`, `test_system`, `test_dataset`) from `tests/api/test_fields.py` into this file, or move them to `tests/api/conftest.py` if that is cleaner.

- [ ] **Step 2: Verify route paths are correct**

Confirm by running: `uv run python -c "from backend.main import app; print([r.path for r in app.routes if '/batch' in r.path])"` — match the URLs in the tests to the actual mounted paths.

- [ ] **Step 3: Run tests**

Run: `make test-docker -- tests/api/test_batch.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_batch.py
git commit -m "test(api): integration tests for batch-create endpoints"
```

---

## Task 8: SDK `create_many`

**Files:**
- Modify: `sdk/aide_sdk/resources/base.py`
- Create: `sdk/tests/test_create_many.py`

- [ ] **Step 1: Write the failing tests**

Create `sdk/tests/test_create_many.py`:

```python
import uuid
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from aide_sdk.resources.base import BaseResource


class _Create(BaseModel):
    name: str


class _Read(BaseModel):
    id: uuid.UUID
    name: str


class _Resource(BaseResource[_Create, _Read, _Create]):
    _path = "/things"
    _read_schema = _Read


def _read_row(name: str) -> dict:
    return {"id": str(uuid.uuid4()), "name": name}


@pytest.mark.asyncio
async def test_create_many_empty_skips_http():
    http = AsyncMock()
    resource = _Resource(http)
    result = await resource.create_many([])
    assert result == []
    http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_many_single_chunk():
    http = AsyncMock()
    http.post = AsyncMock(
        return_value={
            "items": [_read_row("a"), _read_row("b")],
            "count": 2,
        }
    )
    resource = _Resource(http)
    result = await resource.create_many([_Create(name="a"), _Create(name="b")])
    assert len(result) == 2
    assert [r.name for r in result] == ["a", "b"]
    http.post.assert_awaited_once()
    args, kwargs = http.post.call_args
    assert args[0] == "/things/batch"
    assert kwargs["json"] == {"items": [{"name": "a"}, {"name": "b"}]}


@pytest.mark.asyncio
async def test_create_many_chunks_on_size():
    http = AsyncMock()

    calls: list[int] = []

    async def fake_post(path, *, json):
        size = len(json["items"])
        calls.append(size)
        return {
            "items": [_read_row(f"x_{i}") for i in range(size)],
            "count": size,
        }

    http.post = AsyncMock(side_effect=fake_post)
    resource = _Resource(http)

    items = [_Create(name=f"n_{i}") for i in range(1200)]
    result = await resource.create_many(items, chunk_size=500)
    assert len(result) == 1200
    assert calls == [500, 500, 200]


@pytest.mark.asyncio
async def test_create_many_mid_chunk_error_propagates():
    http = AsyncMock()

    async def fake_post(path, *, json):
        if json["items"][0]["name"] == "boom":
            raise RuntimeError("server error")
        size = len(json["items"])
        return {
            "items": [_read_row(i["name"]) for i in json["items"]],
            "count": size,
        }

    http.post = AsyncMock(side_effect=fake_post)
    resource = _Resource(http)

    items = [
        *[_Create(name=f"ok_{i}") for i in range(3)],
        _Create(name="boom"),
    ]
    with pytest.raises(RuntimeError):
        await resource.create_many(items, chunk_size=3)
```

- [ ] **Step 2: Run test**

Run: `cd sdk && uv run pytest tests/test_create_many.py -v`
Expected: FAIL — `create_many` not defined.

- [ ] **Step 3: Implement `create_many`**

Edit `sdk/aide_sdk/resources/base.py`. Add method inside `BaseResource`, after `create`:

```python
    async def create_many(
        self,
        items: list[CreateT],
        *,
        chunk_size: int = 500,
    ) -> list[ReadT]:
        """Create many objects via batch endpoint, auto-chunking.

        All-or-nothing per chunk. If a mid-sequence chunk fails, earlier
        chunks are already committed server-side; the exception propagates
        and earlier-chunk results are NOT returned.
        """
        if not items:
            return []
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")

        from aide_schemas.batch import BatchCreateResponse

        results: list[ReadT] = []
        response_adapter: TypeAdapter[Any] = TypeAdapter(
            BatchCreateResponse[self._read_schema]  # type: ignore[name-defined]
        )
        for start in range(0, len(items), chunk_size):
            chunk = items[start : start + chunk_size]
            data = await self._http.post(
                f"{self._path}/batch",
                json={"items": [x.model_dump(mode="json") for x in chunk]},
            )
            envelope = response_adapter.validate_python(data)
            results.extend(envelope.items)
        return results
```

- [ ] **Step 4: Run tests**

Run: `cd sdk && uv run pytest tests/test_create_many.py -v`
Expected: PASS (all four).

- [ ] **Step 5: Commit**

```bash
git add sdk/aide_sdk/resources/base.py sdk/tests/test_create_many.py
git commit -m "feat(sdk): add BaseResource.create_many with auto-chunking"
```

---

## Task 9: Crawler — batch fields

**Files:**
- Read first: `crawler/aide_crawler/applier.py` (understand existing flow)
- Modify: `crawler/aide_crawler/applier.py`
- Modify: `crawler/tests/test_applier.py`

- [ ] **Step 1: Read current applier flow end-to-end**

Run: `uv run python -c "import pathlib; print(pathlib.Path('crawler/aide_crawler/applier.py').read_text())" | head -400`

Identify:
- The function that creates fields one-by-one (`client.fields.create(...)` calls).
- The function that creates type instance trees recursively.
- The function that creates field bindings.

- [ ] **Step 2: Write the failing test**

Append to `crawler/tests/test_applier.py` (or create a new scoped test file if that is the project convention — check the file first). Use the same `AsyncMock`-based client fixture that the existing tests use. Example assertion pattern:

```python
import pytest
from unittest.mock import AsyncMock

# Follow whatever mock-client setup exists in this file.

@pytest.mark.asyncio
async def test_applier_uses_batch_fields(mock_client_with_dataset):
    """Fields missing on the server are created via a single create_many call."""
    client = mock_client_with_dataset  # whatever the existing fixture name is
    # Arrange: normalized dataset with 5 fields, all missing server-side.
    # Act: run the apply step.
    # Assert:
    client.fields.create_many.assert_awaited_once()
    args, kwargs = client.fields.create_many.call_args
    created_items = args[0] if args else kwargs["items"]
    assert len(created_items) == 5
    # And the per-item create must NOT have been called for those fields:
    assert client.fields.create.await_count == 0
```

- [ ] **Step 3: Run test**

Run: `cd crawler && uv run pytest tests/test_applier.py -v -k batch`
Expected: FAIL — applier still uses `.create(...)` in a loop.

- [ ] **Step 4: Refactor fields creation**

Edit `crawler/aide_crawler/applier.py`. Find the loop that builds missing fields and issues `await client.fields.create(FieldCreate(...))` per item. Replace with:

```python
async def _create_missing_fields(
    client,
    *,
    dataset_id: uuid.UUID,
    existing_by_name: dict[str, uuid.UUID],
    normalized_fields: list,  # whatever the existing type is (NormalizedField)
) -> dict[str, uuid.UUID]:
    """Create any fields missing on the server. Returns full name->id map."""
    to_create: list[FieldCreate] = []
    for nf in normalized_fields:
        if nf.name in existing_by_name:
            continue
        to_create.append(
            FieldCreate(  # type: ignore[call-arg]
                dataset_id=dataset_id,
                name=nf.name,
                ordinal=nf.ordinal,
                # Carry over any other fields the original loop was setting;
                # copy them 1:1 from the pre-refactor code.
            )
        )

    result = dict(existing_by_name)
    if not to_create:
        return result

    created = await client.fields.create_many(to_create)
    for item in created:
        result[item.name] = item.id
    return result
```

Replace the old loop call site with this helper.

- [ ] **Step 5: Run all applier tests**

Run: `cd crawler && uv run pytest tests/test_applier.py -v`
Expected: PASS (new batch test + existing tests still pass).

- [ ] **Step 6: Commit**

```bash
git add crawler/aide_crawler/applier.py crawler/tests/test_applier.py
git commit -m "refactor(crawler): batch-create missing fields via create_many"
```

---

## Task 10: Crawler — batch type_instances by depth

**Files:**
- Modify: `crawler/aide_crawler/applier.py`
- Modify: `crawler/tests/test_applier.py`

- [ ] **Step 1: Study the current `_create_type_instance_tree`**

Locate the recursive function that creates a TypeInstance for a node and its children (in `applier.py`). Note: it returns the root id; children depend on parent's id for `parent_id`.

- [ ] **Step 2: Write the failing test**

Append to `crawler/tests/test_applier.py`:

```python
@pytest.mark.asyncio
async def test_applier_batches_type_instances_by_depth(mock_client_with_dataset):
    """Type instance creation issues one batch call per depth level."""
    client = mock_client_with_dataset
    # Arrange: 3 fields, each with a 2-deep tree (root + 1 child).
    # Act: run applier.

    # Expect depth-0 batch (3 roots), then depth-1 batch (3 children).
    calls = client.type_instances.create_many.await_args_list
    assert len(calls) == 2
    depth0_items = calls[0].args[0] if calls[0].args else calls[0].kwargs["items"]
    depth1_items = calls[1].args[0] if calls[1].args else calls[1].kwargs["items"]
    assert all(it.parent_id is None for it in depth0_items)
    assert all(it.parent_id is not None for it in depth1_items)
    # Children must reference roots created in prior batch call.
    root_ids = {created.id for created in client.type_instances.create_many.side_effect_root_ids}  # adapt to mock shape
    assert all(it.parent_id in root_ids for it in depth1_items)

    # Per-item create must not have been called:
    assert client.type_instances.create.await_count == 0
```

> You will need to adapt the mock to return synthetic `TypeInstanceRead` objects with ids in call order — follow the pattern the existing applier test uses for mocking.

- [ ] **Step 3: Run test**

Run: `cd crawler && uv run pytest tests/test_applier.py -v -k "type_instances"`
Expected: FAIL.

- [ ] **Step 4: Implement topological batching**

Edit `crawler/aide_crawler/applier.py`. Replace `_create_type_instance_tree` and its call site with:

```python
from collections import defaultdict


def _flatten_tree(
    node: TypeNode,
    *,
    path: tuple[str, ...],
    depth: int,
    out: list[tuple[int, tuple[str, ...], tuple[str, ...] | None, TypeNode, str | None]],
) -> None:
    """Append (depth, path, parent_path, node, slot) for each node."""
    parent_path = path[:-1] if path else None
    out.append((depth, path, parent_path, node, path[-1] if path else None))
    for child in node.children:
        _flatten_tree(
            child,
            path=path + (child.slot or child.data_type_code,),
            depth=depth + 1,
            out=out,
        )


async def _batch_create_type_trees(
    client,
    *,
    field_root_nodes: list[tuple[uuid.UUID, TypeNode]],
    type_cache: TypeCache,
) -> dict[uuid.UUID, uuid.UUID]:
    """Create type-instance trees for all fields. Returns {field_id: root_ti_id}.

    Topological: all depth-0 roots first, then depth-1, etc. Each depth level
    is one batch call. Children's parent_id is resolved from the prior level.
    """
    flat: list[tuple[int, tuple[str, ...], tuple[str, ...] | None, TypeNode, str | None]] = []
    # Each field-root node is the depth-0 node for that field. Seed its path
    # with a unique prefix (the field_id) so paths are globally unique.
    field_path_prefix: dict[tuple[str, ...], uuid.UUID] = {}
    for field_id, root in field_root_nodes:
        prefix = (str(field_id),)
        field_path_prefix[prefix] = field_id
        _flatten_tree(root, path=prefix, depth=0, out=flat)

    by_depth: dict[int, list] = defaultdict(list)
    for rec in flat:
        by_depth[rec[0]].append(rec)

    path_to_id: dict[tuple[str, ...], uuid.UUID] = {}
    field_root: dict[uuid.UUID, uuid.UUID] = {}

    for depth in sorted(by_depth.keys()):
        level = by_depth[depth]
        items: list[TypeInstanceCreate] = []
        for _d, _path, parent_path, node, slot in level:
            data_type_id = type_cache.resolve(node.data_type_code)
            allowed = type_cache.allowed_params(node.data_type_code)
            filtered = {k: v for k, v in node.type_params.items() if k in allowed}
            items.append(
                TypeInstanceCreate(  # type: ignore[call-arg]
                    data_type_id=data_type_id,
                    type_params=filtered or None,
                    parent_id=path_to_id[parent_path] if parent_path else None,
                    slot=slot if depth > 0 else None,
                )
            )
        created = await client.type_instances.create_many(items)
        for (_d, path, _pp, _node, _slot), ti in zip(level, created):
            path_to_id[path] = ti.id
            if depth == 0 and len(path) == 1:
                field_id = field_path_prefix[path]
                field_root[field_id] = ti.id

    return field_root
```

Update the apply-dataset flow to collect `(field_id, root_type_node)` pairs for fields that still need a binding, then call `_batch_create_type_trees(...)` once.

- [ ] **Step 5: Run tests**

Run: `cd crawler && uv run pytest tests/test_applier.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add crawler/aide_crawler/applier.py crawler/tests/test_applier.py
git commit -m "refactor(crawler): batch type_instance creation topologically by depth"
```

---

## Task 11: Crawler — batch bindings

**Files:**
- Modify: `crawler/aide_crawler/applier.py`
- Modify: `crawler/tests/test_applier.py`

- [ ] **Step 1: Write the failing test**

Append to `crawler/tests/test_applier.py`:

```python
@pytest.mark.asyncio
async def test_applier_batches_bindings(mock_client_with_dataset):
    client = mock_client_with_dataset
    # Arrange: 4 fields, none yet bound on the server.
    # Act: run applier.
    client.field_bindings.create_many.assert_awaited_once()
    args, kwargs = client.field_bindings.create_many.call_args
    bindings = args[0] if args else kwargs["items"]
    assert len(bindings) == 4
    assert client.field_bindings.create.await_count == 0
```

- [ ] **Step 2: Run test**

Run: `cd crawler && uv run pytest tests/test_applier.py -v -k binding`
Expected: FAIL.

- [ ] **Step 3: Refactor binding creation**

Edit `crawler/aide_crawler/applier.py`. Replace the per-binding loop with:

```python
async def _create_missing_bindings(
    client,
    *,
    schema_id: uuid.UUID,
    field_to_root_ti: dict[uuid.UUID, uuid.UUID],
    already_bound_field_ids: set[uuid.UUID],
) -> int:
    to_create: list[FieldBindingCreate] = []
    for field_id, ti_id in field_to_root_ti.items():
        if field_id in already_bound_field_ids:
            continue
        to_create.append(
            FieldBindingCreate(  # type: ignore[call-arg]
                dataset_schema_id=schema_id,
                field_id=field_id,
                type_instance_id=ti_id,
            )
        )
    if not to_create:
        return 0
    await client.field_bindings.create_many(to_create)
    return len(to_create)
```

Wire it into the apply flow after `_batch_create_type_trees`.

- [ ] **Step 4: Run tests**

Run: `cd crawler && uv run pytest tests/test_applier.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add crawler/aide_crawler/applier.py crawler/tests/test_applier.py
git commit -m "refactor(crawler): batch-create field bindings"
```

---

## Task 12: Full-stack verification

**Files:**
- None (verification only)

- [ ] **Step 1: Lint + type-check**

Run: `make check`
Expected: no errors.

- [ ] **Step 2: Format**

Run: `make format`
Expected: clean; if files were touched, `git add` and amend-or-new-commit per CLAUDE.md rules (create a new commit).

- [ ] **Step 3: Run full backend test suite**

Run: `make test-docker`
Expected: all PASS.

- [ ] **Step 4: Run SDK tests**

Run: `cd sdk && uv run pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Run crawler tests**

Run: `cd crawler && uv run pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 6: End-to-end manual run against `crawler/manual_test/`**

Run: follow `crawler/manual_test/README.md` to run against the local Postgres fixture with an existing `make up` backend.
Expected:
- Crawl succeeds.
- Server logs show `entity.batch_created` events for fields, type_instances, field_bindings — one per depth level plus one for fields and one for bindings.
- No `entity.created` events for those three entity types during the apply phase.

- [ ] **Step 7: Final commit (if any formatting churn)**

```bash
git status
# If any files changed:
git add -A
git commit -m "chore: formatting after batch-create feature"
```

---

## Verification Checklist (plan → spec)

- [x] Generic batch endpoint registered via `create_crud_router` (Task 5) — covers future entities
- [x] All-or-nothing semantics via single UoW (Task 4)
- [x] Order preserved (list comprehension preserves input order in service; `add_all` preserves in repo)
- [x] Max batch size 500 via `settings.MAX_BATCH_SIZE` (Task 2, enforced Task 5)
- [x] Empty batch rejected via `Field(min_length=1)` (Task 1) — 422 surfaces as Pydantic validation error
- [x] Envelope response `{items, count}` (Task 1)
- [x] Wired for fields, type_instances, field_bindings, data_types (Task 6)
- [x] SDK `create_many` with auto-chunking (Task 8)
- [x] Crawler: fields, type_instances (topological by depth), bindings (Tasks 9–11)
- [x] Tests: backend integration, service unit, SDK unit, crawler unit (Tasks 3, 4, 7, 8, 9–11)
- [x] No migrations (confirmed in spec; no schema changes)
