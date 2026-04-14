# Crawler Apply + Type Resolution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the crawler to (1) populate new datasets in the metastore on first encounter and (2) resolve SQLAlchemy types through a metastore-owned DataType catalogue, while existing datasets continue to produce a structured diff only.

**Architecture:** Hybrid type resolution — crawler maps SQLAlchemy class → string `code` locally, metastore owns `data_type_id` resolution and `type_params` validation. Auto-mode: absent datasets are applied, existing ones go to `crawl_run.diff_payload`. Full write chain for apply: `Dataset → DatasetSchema → Field → TypeInstance → FieldBinding`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic v2 (backend). httpx async SDK. SQLAlchemy `Inspector` in crawler. pytest for all tiers.

**Spec:** `docs/superpowers/specs/2026-04-14-crawler-apply-and-type-resolution-design.md`

---

## File Structure

### Backend
- Modify: `backend/models/crawl_run.py` — add `diff_payload` column
- Create: `backend/alembic/versions/<ts>_add_crawl_run_diff_payload.py`
- Modify: `schemas/aide_schemas/crawl_run.py` — `CrawlRunUpdate.diff_payload`, `CrawlRunRead.diff_payload`
- Create: `backend/services/params_schema_validator.py` — pure validator
- Modify: `backend/services/type_instance.py` — call validator in `_pre_create` / `_pre_update`
- Modify: `backend/core/errors.py` — add `TYPE_INSTANCE_PARAMS_INVALID`

### Crawler
- Modify: `crawler/aide_crawler/type_map.py` — exceptions, full PG14 coverage
- Create: `crawler/aide_crawler/type_cache.py` — `TypeCache` class
- Modify: `crawler/aide_crawler/normalizer.py` — add `nullable`, `position` to `NormalizedField`
- Modify: `crawler/aide_crawler/differ.py` — classify + produce `DiffPayload`
- Create: `crawler/aide_crawler/applier.py` — `apply_new_datasets`
- Create: `crawler/aide_crawler/errors.py` — `UnknownTypeError`, `TypeNotInFlavorError`
- Modify: `crawler/aide_crawler/runner.py` — orchestrate cache → normalize → classify → apply → diff → update
- Modify: `crawler/aide_crawler/reporter.py` — render new payload shape

### Tests
- `backend/tests/services/test_params_schema_validator.py` (new)
- `backend/tests/services/test_type_instance_service.py` — extend with validation cases
- `backend/tests/models/test_crawl_run.py` — JSONB round-trip for `diff_payload`
- `crawler/tests/test_type_map.py` (modify)
- `crawler/tests/test_type_cache.py` (new)
- `crawler/tests/test_applier.py` (new)
- `crawler/tests/test_differ.py` (new)
- `crawler/tests/test_runner.py` (new, end-to-end with mocked SDK)

---

## Phase 1 — Backend foundation

### Task 1: Add `diff_payload` column to `crawl_runs`

**Files:**
- Modify: `backend/models/crawl_run.py`
- Create: `backend/alembic/versions/<ts>_add_crawl_run_diff_payload.py`

- [ ] **Step 1: Write the failing test**

File: `backend/tests/models/test_crawl_run.py`

```python
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.crawl_run import CrawlRun


@pytest.mark.asyncio
async def test_diff_payload_roundtrip(db_session: AsyncSession, seed_system):
    run = CrawlRun(
        system_id=seed_system.id,
        status="completed",
        started_at=datetime.now(timezone.utc),
        config={},
        diff_payload={
            "schema_version": 1,
            "new_datasets_applied": [],
            "existing_datasets_diff": [],
            "removed_datasets": [],
        },
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    assert run.diff_payload["schema_version"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test-docker` (filter path or full run — xfail on unknown attribute).
Expected: `TypeError: 'diff_payload' is an invalid keyword argument for CrawlRun`.

- [ ] **Step 3: Add column to the model**

Edit `backend/models/crawl_run.py` — append after `summary`:

```python
    diff_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 4: Generate migration**

Run: `make alembic-gen` (produces a file under `backend/alembic/versions/`).

Review the generated diff. Keep only the `ADD COLUMN diff_payload JSONB NULL` op. Strip any unrelated autogen noise. Rename file if needed to `<ts>_add_crawl_run_diff_payload.py`.

- [ ] **Step 5: Apply migration + rerun test**

```bash
make alembic-head
make test-docker
```

Expected: new test passes.

- [ ] **Step 6: Commit**

```bash
git add backend/models/crawl_run.py backend/alembic/versions/*diff_payload*.py backend/tests/models/test_crawl_run.py
git commit -m "feat(crawl_run): add diff_payload JSONB column"
```

---

### Task 2: Expose `diff_payload` in schemas

**Files:**
- Modify: `schemas/aide_schemas/crawl_run.py`

- [ ] **Step 1: Write the failing test**

File: `backend/tests/api/test_crawl_runs.py` (extend or create)

```python
@pytest.mark.asyncio
async def test_update_crawl_run_with_diff_payload(client, seed_crawl_run):
    payload = {
        "status": "completed",
        "diff_payload": {"schema_version": 1, "new_datasets_applied": []},
        "row_version": seed_crawl_run.row_version,
    }
    resp = await client.patch(f"/api/v1/crawl-runs/{seed_crawl_run.id}", json=payload)
    assert resp.status_code == 200
    assert resp.json()["diff_payload"]["schema_version"] == 1
```

- [ ] **Step 2: Run test**

Run: `make test-docker`.
Expected: 422 — `diff_payload` not in schema.

- [ ] **Step 3: Add fields to schemas**

Edit `schemas/aide_schemas/crawl_run.py`:

```python
class CrawlRunUpdate(VersionedUpdateMixin, NoteMixin):
    status: CrawlStatus | None = None
    finished_at: datetime | None = None
    summary: dict[str, Any] | None = None
    diff_payload: dict[str, Any] | None = None
    error_message: str | None = None


class CrawlRunRead(CrawlRunBase, MetaDataMixin):
    finished_at: datetime | None = None
    summary: dict[str, Any] | None = None
    diff_payload: dict[str, Any] | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: Verify**

Run: `make test-docker` + `make check`.
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add schemas/aide_schemas/crawl_run.py backend/tests/api/test_crawl_runs.py
git commit -m "feat(schemas): diff_payload on CrawlRunUpdate/Read"
```

---

### Task 3: Pure `params_schema` validator

**Files:**
- Create: `backend/services/params_schema_validator.py`
- Create: `backend/tests/services/test_params_schema_validator.py`
- Modify: `backend/core/errors.py`

The validator is deliberately pure (no DB) — unit-testable without fixtures.

Supported `params_schema` entry shape (mirrors YAML in `backend/scripts/data/postgres14.yaml`):
```yaml
key_name:
  type: int | str | bool
  required: bool              # default false
  default: any                # not enforced by validator
  min: number                 # optional, int/float only
  max: number                 # optional, int/float only
```

- [ ] **Step 1: Add error code**

Edit `backend/core/errors.py` — add next to other type_instance codes:

```python
TYPE_INSTANCE_PARAMS_INVALID = "TYPE_INSTANCE_PARAMS_INVALID"
```

And add its message entry in the messages map.

- [ ] **Step 2: Write failing tests**

File: `backend/tests/services/test_params_schema_validator.py`

```python
import pytest

from backend.core.exceptions import AppException
from backend.services.params_schema_validator import validate_type_params


NUMERIC_SCHEMA = {
    "precision": {"type": "int", "required": False, "min": 1, "max": 1000},
    "scale": {"type": "int", "required": False, "min": -1000, "max": 1000},
}


def test_none_params_allowed_for_empty_schema():
    validate_type_params({}, None)


def test_required_missing_raises():
    schema = {"length": {"type": "int", "required": True}}
    with pytest.raises(AppException) as e:
        validate_type_params(schema, {})
    assert "length" in str(e.value)


def test_unknown_key_raises():
    with pytest.raises(AppException):
        validate_type_params(NUMERIC_SCHEMA, {"bogus": 1})


def test_type_mismatch_raises():
    with pytest.raises(AppException):
        validate_type_params(NUMERIC_SCHEMA, {"precision": "oops"})


def test_min_max_bounds():
    with pytest.raises(AppException):
        validate_type_params(NUMERIC_SCHEMA, {"precision": 0})
    with pytest.raises(AppException):
        validate_type_params(NUMERIC_SCHEMA, {"precision": 1001})


def test_happy_path():
    validate_type_params(NUMERIC_SCHEMA, {"precision": 10, "scale": 2})
```

- [ ] **Step 3: Run tests — expect ImportError**

Run: `make test-docker` (tests fail at import).

- [ ] **Step 4: Implement the validator**

File: `backend/services/params_schema_validator.py`

```python
from __future__ import annotations

from typing import Any

from backend.core import errors
from backend.core.exceptions import AppException

_TYPE_MAP: dict[str, type] = {
    "int": int,
    "str": str,
    "bool": bool,
    "float": float,
}


def validate_type_params(
    params_schema: dict[str, Any],
    type_params: dict[str, Any] | None,
) -> None:
    """Validate a TypeInstance.type_params payload against a DataType.params_schema.

    Raises AppException(TYPE_INSTANCE_PARAMS_INVALID) on any violation.
    """
    provided = type_params or {}

    unknown = set(provided) - set(params_schema)
    if unknown:
        raise AppException(
            errors.TYPE_INSTANCE_PARAMS_INVALID,
            detail=f"Unknown params: {sorted(unknown)}",
        )

    for key, rule in params_schema.items():
        required = bool(rule.get("required", False))
        if key not in provided:
            if required:
                raise AppException(
                    errors.TYPE_INSTANCE_PARAMS_INVALID,
                    detail=f"Missing required param '{key}'",
                )
            continue

        value = provided[key]
        if value is None:
            if required:
                raise AppException(
                    errors.TYPE_INSTANCE_PARAMS_INVALID,
                    detail=f"Required param '{key}' is null",
                )
            continue

        expected = _TYPE_MAP.get(rule.get("type", ""))
        if expected is None:
            continue
        if not isinstance(value, expected) or isinstance(value, bool) and expected is int:
            raise AppException(
                errors.TYPE_INSTANCE_PARAMS_INVALID,
                detail=f"Param '{key}' must be {rule['type']}",
            )

        if expected in (int, float):
            low = rule.get("min")
            high = rule.get("max")
            if low is not None and value < low:
                raise AppException(
                    errors.TYPE_INSTANCE_PARAMS_INVALID,
                    detail=f"Param '{key}' below min {low}",
                )
            if high is not None and value > high:
                raise AppException(
                    errors.TYPE_INSTANCE_PARAMS_INVALID,
                    detail=f"Param '{key}' above max {high}",
                )
```

Note: `AppException` currently supports a `detail` kwarg — confirm by reading `backend/core/exceptions.py`. If not, drop `detail=` and rely on the code alone (adjust tests to match).

- [ ] **Step 5: Run tests**

Run: `make test-docker`.
Expected: all new tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/params_schema_validator.py backend/tests/services/test_params_schema_validator.py backend/core/errors.py
git commit -m "feat(types): add pure params_schema validator"
```

---

### Task 4: Wire validator into `TypeInstanceService`

**Files:**
- Modify: `backend/services/type_instance.py`
- Modify: `backend/tests/services/test_type_instance_service.py` (or new file if absent)

- [ ] **Step 1: Write failing tests**

Extend existing test file (check for `backend/tests/services/test_type_instance_service.py` first — create if missing):

```python
@pytest.mark.asyncio
async def test_create_type_instance_rejects_missing_required_param(
    uow_factory, seed_data_type_with_required_length
):
    svc = TypeInstanceService()
    with pytest.raises(AppException) as e:
        await svc.create(
            uow_factory(),
            TypeInstanceCreate(
                data_type_id=seed_data_type_with_required_length.id,
                type_params={},
            ),
            creator_id=None,
        )
    assert e.value.error_code == "TYPE_INSTANCE_PARAMS_INVALID"


@pytest.mark.asyncio
async def test_create_type_instance_accepts_valid_params(
    uow_factory, seed_data_type_numeric
):
    svc = TypeInstanceService()
    created = await svc.create(
        uow_factory(),
        TypeInstanceCreate(
            data_type_id=seed_data_type_numeric.id,
            type_params={"precision": 10, "scale": 2},
        ),
        creator_id=None,
    )
    assert created.type_params == {"precision": 10, "scale": 2}
```

Add conftest fixtures `seed_data_type_with_required_length` (schema with `length: {type: int, required: true}`) and `seed_data_type_numeric` (matches postgres14.yaml numeric entry).

- [ ] **Step 2: Run tests**

Run: `make test-docker`.
Expected: new tests fail because service does not validate yet.

- [ ] **Step 3: Wire validator**

Edit `backend/services/type_instance.py` `_pre_create`, after the `data_type` existence check:

```python
from backend.services.params_schema_validator import validate_type_params
...
        data_type = await uow.data_types.get(obj_in.data_type_id)
        if not data_type:
            raise AppException(errors.DATA_TYPE_NOT_FOUND)
        validate_type_params(data_type.params_schema or {}, obj_in.type_params)
```

(Replace the existing `if not await uow.data_types.get(...)` block — we need the `data_type` value.)

Add symmetric call in `_pre_update` when `type_params` is in `update_data` or when `data_type_id` changes:

```python
        if "type_params" in update_data or "data_type_id" in update_data:
            target_id = update_data.get("data_type_id", db_obj.data_type_id)
            target_type = await uow.data_types.get(target_id)
            if not target_type:
                raise AppException(errors.DATA_TYPE_NOT_FOUND)
            target_params = update_data.get("type_params", db_obj.type_params)
            validate_type_params(target_type.params_schema or {}, target_params)
```

- [ ] **Step 4: Run all backend tests**

Run: `make test-docker`.
Expected: the two new tests pass, existing tests still green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/type_instance.py backend/tests/services/test_type_instance_service.py
git commit -m "feat(type_instance): validate type_params on create/update"
```

---

## Phase 2 — Crawler type resolution

### Task 5: Crawler error module + strict `type_map`

**Files:**
- Create: `crawler/aide_crawler/errors.py`
- Modify: `crawler/aide_crawler/type_map.py`
- Modify: `crawler/tests/test_type_map.py`

- [ ] **Step 1: Create errors module**

File: `crawler/aide_crawler/errors.py`

```python
class CrawlerError(Exception):
    """Base class for crawler-specific errors."""


class UnknownTypeError(CrawlerError):
    def __init__(self, dialect: str, sa_class_name: str):
        super().__init__(
            f"Unknown SQL type: dialect={dialect} sa_class={sa_class_name}"
        )
        self.dialect = dialect
        self.sa_class_name = sa_class_name


class TypeNotInFlavorError(CrawlerError):
    def __init__(self, code: str, flavor_code: str | None = None):
        ctx = f" flavor={flavor_code}" if flavor_code else ""
        super().__init__(f"DataType code '{code}' not found in metastore{ctx}")
        self.code = code
        self.flavor_code = flavor_code
```

- [ ] **Step 2: Write failing tests**

Edit `crawler/tests/test_type_map.py` — replace old expectations. Required coverage:

```python
import pytest
from sqlalchemy import types as sa_types
from sqlalchemy.dialects import postgresql as pg

from aide_crawler.errors import UnknownTypeError
from aide_crawler.type_map import resolve_type


@pytest.mark.parametrize(
    "sa_type,dialect,expected_code",
    [
        (sa_types.SmallInteger(), "postgresql", "smallint"),
        (sa_types.Integer(), "postgresql", "integer"),
        (sa_types.BigInteger(), "postgresql", "bigint"),
        (sa_types.Numeric(10, 2), "postgresql", "numeric"),
        (sa_types.Float(), "postgresql", "real"),
        (sa_types.Double(), "postgresql", "double"),
        (sa_types.String(50), "postgresql", "varchar"),
        (sa_types.Text(), "postgresql", "text"),
        (sa_types.Boolean(), "postgresql", "boolean"),
        (sa_types.Date(), "postgresql", "date"),
        (sa_types.Time(), "postgresql", "time"),
        (sa_types.DateTime(), "postgresql", "timestamp"),
        (sa_types.LargeBinary(), "postgresql", "bytea"),
        (sa_types.Uuid(), "postgresql", "uuid"),
        (pg.JSONB(), "postgresql", "jsonb"),
        (pg.JSON(), "postgresql", "json"),
        (pg.INET(), "postgresql", "inet"),
        (pg.CIDR(), "postgresql", "cidr"),
        (pg.MACADDR(), "postgresql", "macaddr"),
        (pg.INTERVAL(), "postgresql", "interval"),
        (pg.TSVECTOR(), "postgresql", "tsvector"),
        (pg.BYTEA(), "postgresql", "bytea"),
    ],
)
def test_resolve_known_types(sa_type, dialect, expected_code):
    mapping = resolve_type(dialect, sa_type)
    assert mapping.data_type_code == expected_code


def test_numeric_params_extracted():
    mapping = resolve_type("postgresql", sa_types.Numeric(14, 4))
    assert mapping.type_params == {"precision": 14, "scale": 4}


def test_varchar_length_extracted():
    mapping = resolve_type("postgresql", sa_types.String(255))
    assert mapping.type_params == {"length": 255}


def test_unknown_type_raises():
    class Mystery:
        pass

    with pytest.raises(UnknownTypeError):
        resolve_type("postgresql", Mystery())
```

Note: the crawler yaml lists `real` for SA `Float`, `double` for `Double`, `numeric` for `Numeric`. Cross-check against `backend/scripts/data/postgres14.yaml` before finalizing — the mapping must hit codes that exist there.

- [ ] **Step 3: Run tests — expect failures**

```bash
cd crawler && uv run pytest tests/test_type_map.py -v
```

Expected: multiple failures (return-None vs raise, missing pg codes, wrong `Float` mapping).

- [ ] **Step 4: Rewrite `type_map.py`**

File: `crawler/aide_crawler/type_map.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import types as sa_types

from aide_crawler.errors import UnknownTypeError


@dataclass
class TypeMapping:
    data_type_code: str
    type_params: dict[str, Any]


# Generic SA → postgres14 code map. Order matters for isinstance checks:
# put subclasses before parents.
GENERIC_TYPE_MAP: list[tuple[type, str]] = [
    (sa_types.BigInteger, "bigint"),
    (sa_types.SmallInteger, "smallint"),
    (sa_types.Integer, "integer"),
    (sa_types.Boolean, "boolean"),
    (sa_types.Date, "date"),
    (sa_types.Time, "time"),
    (sa_types.DateTime, "timestamp"),
    (sa_types.Double, "double"),
    (sa_types.Float, "real"),
    (sa_types.Numeric, "numeric"),
    (sa_types.LargeBinary, "bytea"),
    (sa_types.Unicode, "varchar"),
    (sa_types.UnicodeText, "text"),
    (sa_types.String, "varchar"),
    (sa_types.Text, "text"),
    (sa_types.Uuid, "uuid"),
    (sa_types.JSON, "json"),
]

DIALECT_TYPE_MAP: dict[tuple[str, str], str] = {
    ("postgresql", "JSONB"): "jsonb",
    ("postgresql", "JSON"): "json",
    ("postgresql", "UUID"): "uuid",
    ("postgresql", "INET"): "inet",
    ("postgresql", "CIDR"): "cidr",
    ("postgresql", "MACADDR"): "macaddr",
    ("postgresql", "INTERVAL"): "interval",
    ("postgresql", "TSVECTOR"): "tsvector",
    ("postgresql", "BYTEA"): "bytea",
    ("postgresql", "ENUM"): "enum",
}


def _extract_params(sa_type: Any) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if getattr(sa_type, "length", None) is not None:
        params["length"] = sa_type.length
    if getattr(sa_type, "precision", None) is not None:
        params["precision"] = sa_type.precision
    if getattr(sa_type, "scale", None) is not None:
        params["scale"] = sa_type.scale
    return params


def resolve_type(dialect_name: str, sa_type: Any) -> TypeMapping:
    """Map a SQLAlchemy type object to (code, params).

    Raises UnknownTypeError if no mapping is found.
    """
    cls_name = type(sa_type).__name__
    code = DIALECT_TYPE_MAP.get((dialect_name, cls_name))
    if code is None:
        for sa_class, generic_code in GENERIC_TYPE_MAP:
            if isinstance(sa_type, sa_class):
                code = generic_code
                break
    if code is None:
        raise UnknownTypeError(dialect_name, cls_name)
    return TypeMapping(data_type_code=code, type_params=_extract_params(sa_type))
```

- [ ] **Step 5: Run tests**

```bash
cd crawler && uv run pytest tests/test_type_map.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add crawler/aide_crawler/errors.py crawler/aide_crawler/type_map.py crawler/tests/test_type_map.py
git commit -m "feat(crawler): strict type_map with exceptions + full pg14 coverage"
```

---

### Task 6: `TypeCache` — flavor-scoped `code → data_type_id`

**Files:**
- Create: `crawler/aide_crawler/type_cache.py`
- Create: `crawler/tests/test_type_cache.py`

- [ ] **Step 1: Write failing tests**

File: `crawler/tests/test_type_cache.py`

```python
import uuid

import pytest

from aide_crawler.errors import TypeNotInFlavorError
from aide_crawler.type_cache import TypeCache


class _Page:
    def __init__(self, items, pages):
        self.items = items
        self.pages = pages


class _Item:
    def __init__(self, id, code):
        self.id = id
        self.code = code


class _DataTypesStub:
    def __init__(self, items):
        self._items = items
        self.calls = []

    async def list(self, *, page=1, size=100, params=None):
        self.calls.append((page, size, params))
        start = (page - 1) * size
        chunk = self._items[start : start + size]
        pages = max(1, (len(self._items) + size - 1) // size)
        return _Page(chunk, pages)


class _ClientStub:
    def __init__(self, items):
        self.data_types = _DataTypesStub(items)


@pytest.mark.asyncio
async def test_load_paginates_and_resolves():
    flavor_id = uuid.uuid4()
    id_int = uuid.uuid4()
    id_num = uuid.uuid4()
    client = _ClientStub([_Item(id_int, "integer"), _Item(id_num, "numeric")])
    cache = await TypeCache.load(client, flavor_id=flavor_id, flavor_code="postgres14")
    assert cache.resolve("integer") == id_int
    assert cache.resolve("numeric") == id_num


@pytest.mark.asyncio
async def test_resolve_missing_raises():
    flavor_id = uuid.uuid4()
    client = _ClientStub([_Item(uuid.uuid4(), "integer")])
    cache = await TypeCache.load(client, flavor_id=flavor_id, flavor_code="postgres14")
    with pytest.raises(TypeNotInFlavorError):
        cache.resolve("jsonb")
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd crawler && uv run pytest tests/test_type_cache.py -v
```

- [ ] **Step 3: Implement `TypeCache`**

File: `crawler/aide_crawler/type_cache.py`

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from aide_crawler.errors import TypeNotInFlavorError


@dataclass
class TypeCache:
    flavor_code: str | None
    _by_code: dict[str, uuid.UUID] = field(default_factory=dict)

    @classmethod
    async def load(
        cls, client, *, flavor_id: uuid.UUID, flavor_code: str | None = None
    ) -> "TypeCache":
        cache = cls(flavor_code=flavor_code)
        page_num = 1
        while True:
            page = await client.data_types.list(
                page=page_num,
                size=100,
                params={"system_flavor_id": str(flavor_id)},
            )
            for item in page.items:
                cache._by_code[item.code] = item.id
            if page_num >= page.pages:
                break
            page_num += 1
        return cache

    def resolve(self, code: str) -> uuid.UUID:
        try:
            return self._by_code[code]
        except KeyError:
            raise TypeNotInFlavorError(code, self.flavor_code) from None

    def __len__(self) -> int:
        return len(self._by_code)
```

- [ ] **Step 4: Run tests**

```bash
cd crawler && uv run pytest tests/test_type_cache.py -v
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add crawler/aide_crawler/type_cache.py crawler/tests/test_type_cache.py
git commit -m "feat(crawler): TypeCache for code→data_type_id resolution"
```

---

## Phase 3 — Crawler apply chain

### Task 7: Extend `NormalizedField` with `nullable` and `position`

**Files:**
- Modify: `crawler/aide_crawler/normalizer.py`
- Modify: `crawler/aide_crawler/inspector.py` (verify it already captures `nullable`)
- Modify: `crawler/tests/test_normalizer.py`

- [ ] **Step 1: Verify inspector already captures nullability**

Read `crawler/aide_crawler/inspector.py`. SA `Inspector.get_columns()` returns dicts with `nullable` — confirm it is propagated into the `InspectionResult.tables[].columns[]`. If not, add it. If yes, proceed.

- [ ] **Step 2: Write failing test**

Edit `crawler/tests/test_normalizer.py` (or add a new test):

```python
def test_normalize_preserves_nullable_and_position(fake_inspection):
    result = normalize(fake_inspection)
    fields = result.datasets[0].fields
    assert fields[0].position == 0
    assert fields[0].nullable is False
    assert fields[1].position == 1
    assert fields[1].nullable is True
```

Create `fake_inspection` fixture that builds `InspectionResult` with two columns (one NOT NULL, one NULL).

- [ ] **Step 3: Run — expect AttributeError**

```bash
cd crawler && uv run pytest tests/test_normalizer.py -v
```

- [ ] **Step 4: Update `NormalizedField` + loop**

Edit `crawler/aide_crawler/normalizer.py`:

```python
@dataclass
class NormalizedField:
    name: str
    path: str
    nullable: bool
    position: int
    type_mapping: TypeMapping
```

In `normalize()`:

```python
        fields = []
        for idx, col in enumerate(table.columns):
            type_mapping = resolve_type(inspection.dialect_name, col.type)
            fields.append(
                NormalizedField(
                    name=col.name,
                    path=col.name,
                    nullable=bool(col.nullable),
                    position=idx,
                    type_mapping=type_mapping,
                )
            )
```

Note: `type_mapping` is no longer `Optional` — `resolve_type` raises on unknown. Propagate the exception.

- [ ] **Step 5: Run tests**

```bash
cd crawler && uv run pytest tests/test_normalizer.py -v
```

- [ ] **Step 6: Commit**

```bash
git add crawler/aide_crawler/normalizer.py crawler/aide_crawler/inspector.py crawler/tests/test_normalizer.py
git commit -m "feat(crawler): nullable+position on NormalizedField"
```

---

### Task 8: `applier.py` — create Dataset+Schema+Field+TypeInstance+FieldBinding

**Files:**
- Create: `crawler/aide_crawler/applier.py`
- Create: `crawler/tests/test_applier.py`

The applier writes the full chain for a new dataset and supports idempotent resume.

- [ ] **Step 1: Write failing tests**

File: `crawler/tests/test_applier.py`

```python
import uuid
from unittest.mock import AsyncMock

import pytest

from aide_crawler.applier import AppliedDataset, apply_new_datasets
from aide_crawler.normalizer import NormalizedDataset, NormalizedField
from aide_crawler.type_cache import TypeCache
from aide_crawler.type_map import TypeMapping


def _field(name, code, position, nullable=True, params=None):
    return NormalizedField(
        name=name,
        path=name,
        nullable=nullable,
        position=position,
        type_mapping=TypeMapping(data_type_code=code, type_params=params or {}),
    )


def _dataset(name="public.users", fields=None):
    return NormalizedDataset(
        object_name=name,
        catalog_name="main",
        schema_name="public",
        table_name=name.split(".")[1],
        is_view=False,
        pk_columns=["id"],
        uq_constraints=[],
        comment=None,
        fields=fields or [_field("id", "bigint", 0, nullable=False)],
        indexes=[],
        foreign_keys=[],
    )


class _Cache(TypeCache):
    def __init__(self):
        super().__init__(flavor_code="postgres14")
        self._by_code = {"bigint": uuid.uuid4(), "varchar": uuid.uuid4()}


def _mock_client():
    c = AsyncMock()
    c.datasets = AsyncMock()
    c.datasets.create = AsyncMock(
        side_effect=lambda payload: type("O", (), {"id": uuid.uuid4()})()
    )
    c.dataset_schemas = AsyncMock()
    c.dataset_schemas.create = AsyncMock(
        side_effect=lambda payload: type("O", (), {"id": uuid.uuid4()})()
    )
    c.fields = AsyncMock()
    c.fields.create = AsyncMock(
        side_effect=lambda payload: type("O", (), {"id": uuid.uuid4(), "name": payload.name})()
    )
    c.fields.list = AsyncMock(
        return_value=type("P", (), {"items": [], "pages": 1})()
    )
    c.type_instances = AsyncMock()
    c.type_instances.create = AsyncMock(
        side_effect=lambda payload: type("O", (), {"id": uuid.uuid4()})()
    )
    c.field_bindings = AsyncMock()
    c.field_bindings.create = AsyncMock(
        side_effect=lambda payload: type("O", (), {"id": uuid.uuid4()})()
    )
    return c


@pytest.mark.asyncio
async def test_apply_creates_full_chain_for_new_dataset():
    client = _mock_client()
    system_id = uuid.uuid4()
    cache = _Cache()
    applied = await apply_new_datasets(
        client, system_id=system_id, datasets=[_dataset()], type_cache=cache
    )
    assert isinstance(applied[0], AppliedDataset)
    client.datasets.create.assert_awaited_once()
    client.dataset_schemas.create.assert_awaited_once()
    client.fields.create.assert_awaited_once()
    client.type_instances.create.assert_awaited_once()
    client.field_bindings.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_is_idempotent_when_fields_already_exist():
    client = _mock_client()
    existing = type("F", (), {"id": uuid.uuid4(), "name": "id"})()
    client.fields.list = AsyncMock(
        return_value=type("P", (), {"items": [existing], "pages": 1})()
    )
    # Partial state: Dataset pre-exists but no DatasetSchema yet.
    pre_existing_dataset = type("D", (), {"id": uuid.uuid4(), "object_name": "public.users"})()
    # Simulate "existing_datasets" being passed in via an optional map so applier
    # knows to reuse the id.
    applied = await apply_new_datasets(
        client,
        system_id=uuid.uuid4(),
        datasets=[_dataset()],
        type_cache=_Cache(),
        existing_dataset_ids={"public.users": pre_existing_dataset.id},
    )
    client.datasets.create.assert_not_awaited()
    client.fields.create.assert_not_awaited()  # field already present
    # But dataset_schema/type_instance/field_binding still must be created.
    client.dataset_schemas.create.assert_awaited_once()
    client.type_instances.create.assert_awaited_once()
    client.field_bindings.create.assert_awaited_once()
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd crawler && uv run pytest tests/test_applier.py -v
```

- [ ] **Step 3: Implement `applier.py`**

File: `crawler/aide_crawler/applier.py`

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass

from aide_schemas.dataset import DatasetRdbmsCreate
from aide_schemas.dataset_schema import DatasetSchemaCreate
from aide_schemas.field import FieldCreate
from aide_schemas.field_binding import FieldBindingCreate
from aide_schemas.type_instance import TypeInstanceCreate

from aide_crawler.normalizer import NormalizedDataset
from aide_crawler.type_cache import TypeCache


@dataclass
class AppliedDataset:
    object_name: str
    dataset_id: uuid.UUID
    dataset_schema_id: uuid.UUID
    fields_count: int


async def _existing_fields(client, dataset_id: uuid.UUID) -> dict[str, uuid.UUID]:
    out: dict[str, uuid.UUID] = {}
    page = 1
    while True:
        resp = await client.fields.list(
            page=page, size=100, params={"dataset_id": str(dataset_id)}
        )
        for f in resp.items:
            out[f.name] = f.id
        if page >= resp.pages:
            break
        page += 1
    return out


async def _apply_one(
    client,
    *,
    system_id: uuid.UUID,
    nd: NormalizedDataset,
    type_cache: TypeCache,
    existing_dataset_id: uuid.UUID | None,
) -> AppliedDataset:
    if existing_dataset_id is None:
        ds = await client.datasets.create(
            DatasetRdbmsCreate(
                kind="rdbms",
                system_id=system_id,
                object_name=nd.object_name,
                catalog_name=nd.catalog_name,
                schema_name=nd.schema_name,
                table_name=nd.table_name,
                is_view=nd.is_view,
                pk_columns=nd.pk_columns or None,
                uq_constraints={"items": nd.uq_constraints} if nd.uq_constraints else None,
            )
        )
        dataset_id = ds.id
    else:
        dataset_id = existing_dataset_id

    schema = await client.dataset_schemas.create(
        DatasetSchemaCreate(dataset_id=dataset_id, version_num=1)
    )

    existing = await _existing_fields(client, dataset_id)

    for nf in nd.fields:
        if nf.name in existing:
            field_id = existing[nf.name]
        else:
            field = await client.fields.create(
                FieldCreate(dataset_id=dataset_id, name=nf.name, path=nf.path)
            )
            field_id = field.id

        data_type_id = type_cache.resolve(nf.type_mapping.data_type_code)
        type_instance = await client.type_instances.create(
            TypeInstanceCreate(
                data_type_id=data_type_id,
                type_params=nf.type_mapping.type_params or None,
            )
        )

        await client.field_bindings.create(
            FieldBindingCreate(
                field_id=field_id,
                dataset_schema_id=schema.id,
                type_instance_id=type_instance.id,
                position=nf.position,
                is_nullable=nf.nullable,
            )
        )

    return AppliedDataset(
        object_name=nd.object_name,
        dataset_id=dataset_id,
        dataset_schema_id=schema.id,
        fields_count=len(nd.fields),
    )


async def apply_new_datasets(
    client,
    *,
    system_id: uuid.UUID,
    datasets: list[NormalizedDataset],
    type_cache: TypeCache,
    existing_dataset_ids: dict[str, uuid.UUID] | None = None,
) -> list[AppliedDataset]:
    existing_dataset_ids = existing_dataset_ids or {}
    applied: list[AppliedDataset] = []
    for nd in datasets:
        applied.append(
            await _apply_one(
                client,
                system_id=system_id,
                nd=nd,
                type_cache=type_cache,
                existing_dataset_id=existing_dataset_ids.get(nd.object_name),
            )
        )
    return applied
```

Note on DatasetSchema idempotency: if a `DatasetSchema(version_num=1)` already exists for the dataset, the create will return a conflict. Handle this by wrapping the schema-create in `try/except ConflictError` from `aide_sdk.exceptions` and fetching the existing schema via `client.dataset_schemas.list(params={"dataset_id": ...})`. Implement this refinement only if tests exercise it — keep the first pass minimal.

- [ ] **Step 4: Run tests**

```bash
cd crawler && uv run pytest tests/test_applier.py -v
```

Expected: green. If the idempotent test reveals the DatasetSchema conflict path, add the try/except now.

- [ ] **Step 5: Commit**

```bash
git add crawler/aide_crawler/applier.py crawler/tests/test_applier.py
git commit -m "feat(crawler): applier writes full dataset chain"
```

---

## Phase 4 — Differ, runner, reporter

### Task 9: Refactor `differ.py` to classify + produce `DiffPayload`

**Files:**
- Modify: `crawler/aide_crawler/differ.py`
- Create: `crawler/tests/test_differ.py`

The differ splits crawled datasets into `to_apply` (absent in metastore) and `to_diff` (present), and for existing datasets builds the structured diff. **No type comparison in v1** — `type_changes` starts empty and can be filled in a follow-up once we can read FieldBinding.type_instance for a given schema. Leave an explicit TODO in code.

- [ ] **Step 1: Write failing tests**

File: `crawler/tests/test_differ.py`

```python
import uuid
from unittest.mock import AsyncMock

import pytest

from aide_crawler.differ import DiffPayload, classify_and_diff
from aide_crawler.normalizer import NormalizedDataset, NormalizedField, NormalizedResult
from aide_crawler.type_map import TypeMapping


def _nf(name, code="bigint", position=0):
    return NormalizedField(
        name=name,
        path=name,
        nullable=False,
        position=position,
        type_mapping=TypeMapping(data_type_code=code, type_params={}),
    )


def _nd(name, fields):
    return NormalizedDataset(
        object_name=name,
        catalog_name=None,
        schema_name=name.split(".")[0],
        table_name=name.split(".")[1],
        is_view=False,
        pk_columns=[],
        uq_constraints=[],
        comment=None,
        fields=fields,
        indexes=[],
        foreign_keys=[],
    )


def _mock_client(existing_datasets, existing_fields):
    c = AsyncMock()
    c.datasets = AsyncMock()
    c.datasets.list = AsyncMock(
        return_value=type(
            "P",
            (),
            {
                "items": [
                    type("D", (), {"model_dump": lambda self=d: d})() for d in existing_datasets
                ],
                "pages": 1,
            },
        )()
    )
    c.fields = AsyncMock()
    c.fields.list = AsyncMock(
        return_value=type(
            "P",
            (),
            {
                "items": [
                    type("F", (), {"model_dump": lambda self=f: f})() for f in existing_fields
                ],
                "pages": 1,
            },
        )()
    )
    return c


@pytest.mark.asyncio
async def test_all_new():
    client = _mock_client(existing_datasets=[], existing_fields=[])
    normalized = NormalizedResult(
        dialect_name="postgresql",
        datasets=[_nd("public.users", [_nf("id")])],
    )
    to_apply, payload = await classify_and_diff(client, uuid.uuid4(), normalized)
    assert [d.object_name for d in to_apply] == ["public.users"]
    assert payload.existing_datasets_diff == []
    assert payload.removed_datasets == []


@pytest.mark.asyncio
async def test_existing_new_field_diff():
    ds_id = uuid.uuid4()
    client = _mock_client(
        existing_datasets=[{"id": ds_id, "object_name": "public.users"}],
        existing_fields=[{"id": uuid.uuid4(), "name": "id"}],
    )
    normalized = NormalizedResult(
        dialect_name="postgresql",
        datasets=[_nd("public.users", [_nf("id"), _nf("email", position=1)])],
    )
    to_apply, payload = await classify_and_diff(client, uuid.uuid4(), normalized)
    assert to_apply == []
    assert payload.existing_datasets_diff[0]["new_fields"][0]["name"] == "email"


@pytest.mark.asyncio
async def test_removed_dataset_listed():
    client = _mock_client(
        existing_datasets=[{"id": uuid.uuid4(), "object_name": "public.old"}],
        existing_fields=[],
    )
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[])
    to_apply, payload = await classify_and_diff(client, uuid.uuid4(), normalized)
    assert payload.removed_datasets[0]["object_name"] == "public.old"


def test_payload_to_dict_schema_version():
    payload = DiffPayload(
        new_datasets_applied=[], existing_datasets_diff=[], removed_datasets=[]
    )
    d = payload.to_dict()
    assert d["schema_version"] == 1
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd crawler && uv run pytest tests/test_differ.py -v
```

- [ ] **Step 3: Rewrite `differ.py`**

File: `crawler/aide_crawler/differ.py`

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from aide_sdk import AideClient

from aide_crawler.normalizer import NormalizedDataset, NormalizedResult


@dataclass
class DiffPayload:
    new_datasets_applied: list[dict[str, Any]] = field(default_factory=list)
    existing_datasets_diff: list[dict[str, Any]] = field(default_factory=list)
    removed_datasets: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, **asdict(self)}

    def counts(self) -> dict[str, int]:
        return {
            "new_datasets_applied": len(self.new_datasets_applied),
            "new_fields": sum(
                len(e["new_fields"]) for e in self.existing_datasets_diff
            ),
            "removed_fields": sum(
                len(e["removed_fields"]) for e in self.existing_datasets_diff
            ),
            "removed_datasets": len(self.removed_datasets),
            "type_changes": sum(
                len(e.get("type_changes", [])) for e in self.existing_datasets_diff
            ),
        }


async def _list_existing_datasets(
    client: AideClient, system_id: UUID
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        resp = await client.datasets.list(
            page=page, size=100, params={"system_id": str(system_id)}
        )
        for item in resp.items:
            ds = item.model_dump()
            out[ds["object_name"]] = ds
        if page >= resp.pages:
            break
        page += 1
    return out


async def _list_existing_fields(
    client: AideClient, dataset_id: UUID
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        resp = await client.fields.list(
            page=page, size=100, params={"dataset_id": str(dataset_id)}
        )
        for item in resp.items:
            f = item.model_dump()
            out[f["name"]] = f
        if page >= resp.pages:
            break
        page += 1
    return out


async def classify_and_diff(
    client: AideClient, system_id: UUID, normalized: NormalizedResult
) -> tuple[list[NormalizedDataset], DiffPayload]:
    """Split crawled datasets into (to_apply, diff_payload).

    TODO: type_changes is left empty — requires DatasetSchema→FieldBinding
    traversal to compare old vs new (code, params). Follow-up task.
    """
    existing = await _list_existing_datasets(client, system_id)
    existing_names = set(existing)
    crawled_names = {d.object_name for d in normalized.datasets}

    payload = DiffPayload()
    to_apply: list[NormalizedDataset] = [
        d for d in normalized.datasets if d.object_name not in existing_names
    ]

    for name in existing_names - crawled_names:
        payload.removed_datasets.append(
            {"object_name": name, "dataset_id": str(existing[name]["id"])}
        )

    for nd in normalized.datasets:
        if nd.object_name not in existing_names:
            continue
        ds = existing[nd.object_name]
        ds_id = ds["id"]
        existing_fields = await _list_existing_fields(client, ds_id)

        crawled_names_set = {f.name for f in nd.fields}
        new_fields = [
            {
                "name": f.name,
                "code": f.type_mapping.data_type_code,
                "params": f.type_mapping.type_params or {},
            }
            for f in nd.fields
            if f.name not in existing_fields
        ]
        removed_fields = [
            {"name": name, "field_id": str(existing_fields[name]["id"])}
            for name in set(existing_fields) - crawled_names_set
        ]
        entry = {
            "object_name": nd.object_name,
            "dataset_id": str(ds_id),
            "new_fields": new_fields,
            "removed_fields": removed_fields,
            "type_changes": [],  # TODO: compare via FieldBinding.type_instance
        }
        payload.existing_datasets_diff.append(entry)

    return to_apply, payload
```

- [ ] **Step 4: Run tests**

```bash
cd crawler && uv run pytest tests/test_differ.py -v
```

- [ ] **Step 5: Commit**

```bash
git add crawler/aide_crawler/differ.py crawler/tests/test_differ.py
git commit -m "refactor(crawler): differ returns (to_apply, DiffPayload)"
```

---

### Task 10: Rewire `runner.py` around new pipeline

**Files:**
- Modify: `crawler/aide_crawler/runner.py`
- Create: `crawler/tests/test_runner.py`

- [ ] **Step 1: Write failing test**

File: `crawler/tests/test_runner.py`

```python
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from aide_crawler.runner import run_crawl


@pytest.mark.asyncio
async def test_runner_updates_crawl_run_with_payload(monkeypatch):
    system_id = uuid.uuid4()
    flavor_id = uuid.uuid4()
    crawl_run_id = uuid.uuid4()

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    fake_client.systems.list = AsyncMock(
        return_value=type(
            "P",
            (),
            {
                "items": [
                    type("S", (), {"id": system_id, "flavor_id": flavor_id})()
                ],
                "total": 1,
            },
        )()
    )
    fake_client.data_types.list = AsyncMock(
        return_value=type(
            "P",
            (),
            {
                "items": [type("I", (), {"id": uuid.uuid4(), "code": "bigint"})()],
                "pages": 1,
                "total": 1,
            },
        )()
    )
    fake_client.crawl_runs.create = AsyncMock(
        return_value=type("R", (), {"id": crawl_run_id, "row_version": 0})()
    )
    fake_client.crawl_runs.update = AsyncMock()
    fake_client.datasets.list = AsyncMock(
        return_value=type("P", (), {"items": [], "pages": 1})()
    )

    # Short-circuit inspection + apply with stubs that return empty.
    monkeypatch.setattr(
        "aide_crawler.runner.run_inspection",
        lambda *a, **k: type("I", (), {"dialect_name": "postgresql", "tables": []})(),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.normalize",
        lambda _: type("R", (), {"dialect_name": "postgresql", "datasets": []})(),
    )

    with patch("aide_crawler.runner.AideClient", return_value=fake_client):
        await run_crawl(
            system_code="sys",
            connection_url="postgresql://",
            metastore_url="http://m",
            metastore_user="u",
            metastore_password="p",
        )

    update_call = fake_client.crawl_runs.update.await_args
    _, kwargs_or_model = update_call.args[0], update_call.args[1]
    # second arg is CrawlRunUpdate — assert diff_payload is present and status completed.
    assert kwargs_or_model.status.value == "completed"
    assert kwargs_or_model.diff_payload["schema_version"] == 1
```

- [ ] **Step 2: Run — expect AttributeError / shape mismatch**

```bash
cd crawler && uv run pytest tests/test_runner.py -v
```

- [ ] **Step 3: Rewrite `runner.py`**

Replace contents of `crawler/aide_crawler/runner.py` — key diff:
- import `TypeCache`, `classify_and_diff`, `apply_new_datasets`
- after `data_types.list` check, build `type_cache = await TypeCache.load(client, flavor_id=flavor_id, flavor_code=system.flavor_code if hasattr(system, "flavor_code") else None)`
- replace `compute_diff` call with `to_apply, payload = await classify_and_diff(...)`
- call `applied = await apply_new_datasets(client, system_id=system_id, datasets=to_apply, type_cache=type_cache)` and `payload.new_datasets_applied = [asdict(a) for a in applied]`
- update `crawl_run.update(...)` with `summary=payload.counts(), diff_payload=payload.to_dict()`
- failure branch unchanged

Skeleton:

```python
from dataclasses import asdict
...
        flavor_id = system.flavor_id
        dt_page = await client.data_types.list(
            params={"system_flavor_id": str(flavor_id)}
        )
        if dt_page.total == 0:
            print("Error: No DataTypes found for system flavor. Seed DataTypes before crawling.", file=sys.stderr)
            raise SystemExit(1)

        type_cache = await TypeCache.load(
            client, flavor_id=flavor_id, flavor_code=None
        )

        crawl_run = await client.crawl_runs.create(...)  # unchanged

        try:
            inspection = run_inspection(...)
            normalized = normalize(inspection)
            to_apply, payload = await classify_and_diff(client, system_id, normalized)
            applied = await apply_new_datasets(
                client, system_id=system_id, datasets=to_apply, type_cache=type_cache
            )
            payload.new_datasets_applied = [
                {
                    "object_name": a.object_name,
                    "dataset_id": str(a.dataset_id),
                    "fields_count": a.fields_count,
                }
                for a in applied
            ]

            if output_file:
                with open(output_file, "w") as f:
                    format_report(payload, output_format, f)
            else:
                format_report(payload, output_format)

            await client.crawl_runs.update(
                crawl_run.id,
                CrawlRunUpdate(
                    status=CrawlStatus.COMPLETED,
                    finished_at=datetime.now(timezone.utc),
                    summary=payload.counts(),
                    diff_payload=payload.to_dict(),
                    row_version=crawl_run.row_version,
                ),
            )
        except Exception as exc:
            await client.crawl_runs.update(
                crawl_run.id,
                CrawlRunUpdate(
                    status=CrawlStatus.FAILED,
                    finished_at=datetime.now(timezone.utc),
                    error_message=str(exc),
                    row_version=crawl_run.row_version,
                ),
            )
            raise
```

Replace the string `"running"`/`"completed"`/`"failed"` with `CrawlStatus` enum values. Update the `CrawlRunCreate(..., status="running")` call to `CrawlStatus.RUNNING`.

- [ ] **Step 4: Run tests**

```bash
cd crawler && uv run pytest tests/test_runner.py -v
```

- [ ] **Step 5: Commit**

```bash
git add crawler/aide_crawler/runner.py crawler/tests/test_runner.py
git commit -m "feat(crawler): runner orchestrates apply+diff with TypeCache"
```

---

### Task 11: Update `reporter.py` for new payload shape

**Files:**
- Modify: `crawler/aide_crawler/reporter.py`
- Modify: `crawler/tests/test_reporter.py`

- [ ] **Step 1: Write failing test**

Edit `crawler/tests/test_reporter.py`:

```python
from io import StringIO

from aide_crawler.differ import DiffPayload
from aide_crawler.reporter import format_report


def test_report_text_lists_applied_and_diff():
    payload = DiffPayload(
        new_datasets_applied=[
            {"object_name": "public.users", "dataset_id": "x", "fields_count": 3}
        ],
        existing_datasets_diff=[
            {
                "object_name": "public.orders",
                "dataset_id": "y",
                "new_fields": [{"name": "shipped_at", "code": "timestamp", "params": {}}],
                "removed_fields": [],
                "type_changes": [],
            }
        ],
        removed_datasets=[],
    )
    buf = StringIO()
    format_report(payload, "text", buf)
    out = buf.getvalue()
    assert "Applied: public.users" in out
    assert "public.orders" in out
    assert "shipped_at" in out


def test_report_json_emits_schema_version():
    payload = DiffPayload()
    buf = StringIO()
    format_report(payload, "json", buf)
    assert '"schema_version": 1' in buf.getvalue()
```

- [ ] **Step 2: Run — expect failures**

```bash
cd crawler && uv run pytest tests/test_reporter.py -v
```

- [ ] **Step 3: Rewrite `reporter.py`**

```python
from __future__ import annotations

import json
import sys
from typing import IO

from aide_crawler.differ import DiffPayload


def report_text(payload: DiffPayload, out: IO[str] = sys.stdout) -> None:
    out.write("=== AIDE Crawler Report ===\n\n")

    if payload.new_datasets_applied:
        out.write(f"--- Applied ({len(payload.new_datasets_applied)}) ---\n")
        for d in payload.new_datasets_applied:
            out.write(f"  Applied: {d['object_name']}  [{d['fields_count']} fields]\n")
        out.write("\n")

    if payload.existing_datasets_diff:
        out.write(
            f"--- Existing datasets with changes ({len(payload.existing_datasets_diff)}) ---\n"
        )
        for e in payload.existing_datasets_diff:
            out.write(f"  * {e['object_name']}\n")
            for nf in e["new_fields"]:
                out.write(f"      + {nf['name']} ({nf['code']})\n")
            for rf in e["removed_fields"]:
                out.write(f"      - {rf['name']}\n")
            for tc in e.get("type_changes", []):
                out.write(
                    f"      ~ {tc['field_name']}: {tc['old']['code']} -> {tc['new']['code']}\n"
                )
        out.write("\n")

    if payload.removed_datasets:
        out.write(f"--- Removed datasets ({len(payload.removed_datasets)}) ---\n")
        for d in payload.removed_datasets:
            out.write(f"  - {d['object_name']}\n")
        out.write("\n")

    counts = payload.counts()
    out.write("--- Summary ---\n")
    for k, v in counts.items():
        out.write(f"  {k}: {v}\n")


def report_json(payload: DiffPayload, out: IO[str] = sys.stdout) -> None:
    json.dump(payload.to_dict(), out, indent=2, default=str)
    out.write("\n")


def format_report(
    payload: DiffPayload, fmt: str, out: IO[str] = sys.stdout
) -> None:
    if fmt == "json":
        report_json(payload, out)
    else:
        report_text(payload, out)
```

- [ ] **Step 4: Run tests**

```bash
cd crawler && uv run pytest tests/ -v
```

Expected: all crawler tests green.

- [ ] **Step 5: Commit**

```bash
git add crawler/aide_crawler/reporter.py crawler/tests/test_reporter.py
git commit -m "refactor(crawler): reporter consumes DiffPayload"
```

---

## Phase 5 — Verification

### Task 12: Full lint + backend + crawler test sweep

- [ ] **Step 1: Backend**

```bash
make format
make check
make test-docker
```

Expected: everything green.

- [ ] **Step 2: Crawler**

```bash
cd crawler && uv run pytest tests/ -v
cd ..
```

Expected: all crawler tests pass.

- [ ] **Step 3: Commit any formatting churn**

```bash
git status
# if dirty:
git add -u
git commit -m "style: make format"
```

---

### Task 13: Manual smoke (golden path)

- [ ] **Step 1: Bring up stack with empty metastore**

```bash
make up
# in another terminal: seed flavor + data types for postgres14
uv run python -m backend.scripts.seed_data_types --file backend/scripts/data/postgres14.yaml
```

- [ ] **Step 2: Prepare a tiny source PG**

Spin up any PG14 with 2–3 tables. Note its URL.

- [ ] **Step 3: Create a System in metastore with `flavor=postgres14`**

Either via UI or SDK — outside this plan's scope.

- [ ] **Step 4: First crawl — expect all datasets applied**

```bash
cd crawler && uv run aide-crawler \
  --system-code <code> \
  --connection-url <source-url> \
  --metastore-url http://localhost:8001 \
  --metastore-user <u> --metastore-password <p> \
  --output-format json
```

Expected output JSON: `new_datasets_applied` non-empty, `existing_datasets_diff` empty. Verify via `GET /api/v1/datasets?system_id=...` that datasets and fields exist.

- [ ] **Step 5: Second crawl without changes — expect empty diff**

Rerun the same command. Expected: `new_datasets_applied == []`, `existing_datasets_diff == []`.

- [ ] **Step 6: Add a column at source, rerun**

`ALTER TABLE public.users ADD COLUMN extra text;` → rerun. Expected: `existing_datasets_diff[0].new_fields` contains `extra`.

- [ ] **Step 7: Drop a column, rerun**

Expected: `removed_fields` populated. Dataset not deleted from metastore.

- [ ] **Step 8: Negative — unseeded type**

Use a type absent from `postgres14.yaml` (e.g. `CITEXT`). Expected: crawl fails, `crawl_run.status=failed`, `error_message` mentions `UnknownTypeError` or `TypeNotInFlavorError`.

- [ ] **Step 9: Commit nothing (manual run only)**

Record outcome in a short note if something unexpected surfaced — file a follow-up task.

---

## Open items (follow-ups, out of scope for this plan)

- `type_changes` computation in diff (requires reading `FieldBinding.type_instance` for the current `DatasetSchema` version). Left as TODO in `differ.py`.
- Auto-soft-delete of removed datasets/fields — explicitly out of scope per spec.
- Nested/struct field handling (JSON schema introspection) — untouched.
- Partial-apply recovery for killed runs — baseline idempotency covers most cases; improve if pain emerges.

---

## Self-review notes

- Every spec section has at least one task.
- No placeholders — where a follow-up is genuinely deferred (type_changes), it is flagged as open item and as an inline TODO, not a missing step.
- Types stay consistent: `TypeCache.resolve`, `DiffPayload`, `AppliedDataset`, `NormalizedField.{nullable,position}` are used the same way everywhere they appear.
- Scope: one plan, one worktree, one spec. Acceptable size.
