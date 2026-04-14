# RDBMS Metadata Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an RDBMS metadata crawler with shared schemas package, Python SDK, and CLI crawler tool that introspects databases via SQLAlchemy Inspector and produces diff reports against the AIDE metastore.

**Architecture:** Four sequential phases — (1) CrawlRun entity in backend, (2) shared Pydantic schemas package extracted from backend, (3) async SDK wrapping the REST API, (4) crawler CLI with inspect/normalize/diff/report pipeline. Each phase produces working, testable software.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0, Pydantic, httpx, Typer, uv

**Spec:** `docs/superpowers/specs/2026-04-13-rdbms-crawler-design.md`

---

## Phase 1: CrawlRun Backend Entity

Adds the CrawlRun model, repository, service, schemas, router, and migration to the existing backend. Follows established patterns exactly (CastRule as reference).

---

### Task 1: CrawlRun Model + Alembic Migration

**Files:**
- Create: `backend/models/crawl_run.py`
- Modify: `backend/models/__init__.py`
- Migration auto-generated via alembic

- [ ] **Step 1: Create the CrawlRun model**

```python
# backend/models/crawl_run.py
import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class CrawlStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CrawlRun(Base, MetaDataMixin):
    __tablename__ = "crawl_runs"

    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("systems.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    system = relationship("System", foreign_keys=[system_id])

    def __repr__(self) -> str:
        return f"CrawlRun(id={self.id}, system_id={self.system_id}, status={self.status})"
```

- [ ] **Step 2: Register model in `__init__.py`**

Add to `backend/models/__init__.py`:
```python
from .crawl_run import CrawlRun, CrawlStatus
```

Add `"CrawlRun"` and `"CrawlStatus"` to `__all__`.

- [ ] **Step 3: Generate alembic migration**

Run: `make alembic-gen`

Verify the generated migration creates `crawl_runs` table with correct columns and FK to `systems.id`.

- [ ] **Step 4: Apply migration**

Run: `make alembic-head`

- [ ] **Step 5: Commit**

```bash
git add backend/models/crawl_run.py backend/models/__init__.py backend/alembic/versions/
git commit -m "feat: add CrawlRun model and migration"
```

---

### Task 2: CrawlRun Pydantic Schemas

**Files:**
- Create: `backend/schemas/crawl_run.py`
- Modify: `backend/schemas/__init__.py`

- [ ] **Step 1: Create CrawlRun schemas**

```python
# backend/schemas/crawl_run.py
import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class CrawlStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CrawlRunBase(BaseModel):
    system_id: uuid.UUID
    status: CrawlStatus
    started_at: datetime
    config: dict[str, Any]


class CrawlRunCreate(CrawlRunBase, NoteMixin):
    pass


class CrawlRunUpdate(VersionedUpdateMixin, NoteMixin):
    status: CrawlStatus | None = None
    finished_at: datetime | None = None
    summary: dict[str, Any] | None = None
    error_message: str | None = None


class CrawlRunRead(CrawlRunBase, MetaDataMixin):
    finished_at: datetime | None = None
    summary: dict[str, Any] | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: Register in schemas `__init__.py`**

Add to `backend/schemas/__init__.py`:
```python
from .crawl_run import CrawlRunCreate, CrawlRunRead, CrawlRunUpdate
```

Add `"CrawlRunCreate"`, `"CrawlRunRead"`, `"CrawlRunUpdate"` to `__all__`.

- [ ] **Step 3: Commit**

```bash
git add backend/schemas/crawl_run.py backend/schemas/__init__.py
git commit -m "feat: add CrawlRun Pydantic schemas"
```

---

### Task 3: CrawlRun Repository

**Files:**
- Create: `backend/repositories/crawl_run.py`
- Modify: `backend/db/uow.py`

- [ ] **Step 1: Create CrawlRun repository**

```python
# backend/repositories/crawl_run.py
from backend.models.crawl_run import CrawlRun
from backend.repositories.base import BaseRepository


class CrawlRunRepository(BaseRepository[CrawlRun]):
    model = CrawlRun
```

- [ ] **Step 2: Register in UnitOfWork**

Add to `backend/db/uow.py`:

Import:
```python
from backend.repositories.crawl_run import CrawlRunRepository
```

In `__aenter__`, add:
```python
self.crawl_runs = CrawlRunRepository(self.session)
```

- [ ] **Step 3: Commit**

```bash
git add backend/repositories/crawl_run.py backend/db/uow.py
git commit -m "feat: add CrawlRun repository and register in UoW"
```

---

### Task 4: CrawlRun Error Codes + Filter

**Files:**
- Modify: `backend/core/errors.py`
- Modify: `backend/schemas/filters.py`

- [ ] **Step 1: Add error codes**

Add to `backend/core/errors.py` constants section:
```python
CRAWL_RUN_NOT_FOUND = "CRAWL_RUN_NOT_FOUND"
```

Add to `ERROR_MAP`:
```python
CRAWL_RUN_NOT_FOUND: (
    status.HTTP_404_NOT_FOUND,
    "The requested crawl run was not found.",
),
```

- [ ] **Step 2: Add filter model**

Add to `backend/schemas/filters.py`:
```python
# ── CrawlRun ────────────────────────────────────────────────────────────
class CrawlRunFilter(BaseFilter):
    system_id: uuid.UUID | None = None
    status: str | None = None
    status__in: str | None = None
    started_at__gte: datetime | None = None
    started_at__lte: datetime | None = None


CRAWL_RUN_SORTABLE = {"status", "started_at", "finished_at", "created_at"}
```

- [ ] **Step 3: Commit**

```bash
git add backend/core/errors.py backend/schemas/filters.py
git commit -m "feat: add CrawlRun error codes and filter model"
```

---

### Task 5: CrawlRun Service

**Files:**
- Create: `backend/services/crawl_run.py`

- [ ] **Step 1: Create CrawlRun service**

```python
# backend/services/crawl_run.py
import uuid

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.crawl_run import CrawlRun
from backend.repositories.crawl_run import CrawlRunRepository
from backend.schemas.crawl_run import (
    CrawlRunCreate,
    CrawlRunRead,
    CrawlRunUpdate,
)
from backend.services.base import GenericService


class CrawlRunService(
    GenericService[CrawlRun, CrawlRunCreate, CrawlRunUpdate, CrawlRunRead]
):
    def __init__(self):
        super().__init__(
            model=CrawlRun,
            repository=CrawlRunRepository,
            read_schema=CrawlRunRead,
            not_found_error_code=errors.CRAWL_RUN_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: CrawlRunCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        if not await uow.systems.get(obj_in.system_id):
            raise AppException(errors.SYSTEM_NOT_FOUND)
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/crawl_run.py
git commit -m "feat: add CrawlRun service"
```

---

### Task 6: CrawlRun Router + Wire in main.py

**Files:**
- Create: `backend/api/v1/crawl_runs.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Create CrawlRun router**

Note: CrawlRun is an audit log — no DELETE, no restore. Use `create_crud_router` with filter support but override delete by not including it. Actually, looking at the crud_router factory, it always includes DELETE. For CrawlRun we need a custom router without DELETE.

```python
# backend/api/v1/crawl_runs.py
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import (
    get_current_user,
)
from backend.api.filter_sort import (
    FilterSortParams,
    get_filter_sort_dependency,
)
from backend.core.errors import (
    CRAWL_RUN_NOT_FOUND,
    SYSTEM_NOT_FOUND,
    UNAUTHORIZED,
    FORBIDDEN,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.crawl_run import (
    CrawlRunCreate,
    CrawlRunRead,
    CrawlRunUpdate,
)
from backend.schemas.filters import CRAWL_RUN_SORTABLE, CrawlRunFilter
from backend.schemas.pagination import Page
from backend.services.crawl_run import CrawlRunService

router = APIRouter()

_filter_sort_dep = get_filter_sort_dependency(
    CrawlRunFilter, CRAWL_RUN_SORTABLE, "started_at"
)


@router.get(
    "/",
    response_model=Page[CrawlRunRead],
    summary="Get all crawl runs (paginated)",
)
async def get_all(
    service: CrawlRunService = Depends(CrawlRunService),
    uow: UnitOfWork = Depends(UnitOfWork),
    params: FilterSortParams = Depends(_filter_sort_dep),
) -> Any:
    return await service.get_paginated(
        uow=uow,
        page=params.page,
        size=params.size,
        filters=params.filters,
        sort=params.sort,
    )


@router.post(
    "/",
    response_model=CrawlRunRead,
    status_code=201,
    summary="Create a crawl run",
    responses={**build_error_responses(SYSTEM_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def create(
    obj_in: CrawlRunCreate,
    service: CrawlRunService = Depends(CrawlRunService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.get(
    "/{obj_id}",
    response_model=CrawlRunRead,
    summary="Get a crawl run by ID",
    responses={**build_error_responses(CRAWL_RUN_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def get_one(
    obj_id: uuid.UUID,
    service: CrawlRunService = Depends(CrawlRunService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    return await service.get_by_id(uow=uow, obj_id=obj_id)


@router.put(
    "/{obj_id}",
    response_model=CrawlRunRead,
    summary="Update a crawl run",
    responses={
        **build_error_responses(
            CRAWL_RUN_NOT_FOUND, VERSION_CONFLICT, UNAUTHORIZED, FORBIDDEN
        )
    },
)
async def update(
    obj_id: uuid.UUID,
    obj_in: CrawlRunUpdate,
    service: CrawlRunService = Depends(CrawlRunService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )
```

- [ ] **Step 2: Wire router in main.py**

Add to `backend/main.py`:

Import:
```python
from backend.api.v1 import crawl_runs as v1_crawl_runs
```

Add router registration (after type-instances):
```python
app.include_router(
    v1_crawl_runs.router,
    prefix=f"{api_v1_prefix}/crawl-runs",
    tags=["Crawl Runs"],
)
```

- [ ] **Step 3: Run lint + type check**

Run: `make check`

Fix any issues.

- [ ] **Step 4: Run format**

Run: `make format`

- [ ] **Step 5: Commit**

```bash
git add backend/api/v1/crawl_runs.py backend/main.py
git commit -m "feat: add CrawlRun API router and wire in main.py"
```

---

### Task 7: CrawlRun API Tests

**Files:**
- Create: `tests/api/test_crawl_runs.py`

- [ ] **Step 1: Write CrawlRun API tests**

```python
# tests/api/test_crawl_runs.py
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.security import get_password_hash
from backend.main import app
from backend.models import (
    CrawlRun,
    System,
    SystemFlavor,
    SystemKind,
    User,
)


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="crawl_super@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
        is_superuser=True,
    )
    transactional_session.add(user)
    await transactional_session.commit()
    await transactional_session.refresh(user)
    return user


@pytest.fixture
async def superuser_token_headers(
    async_client: AsyncClient, superuser: User
) -> dict[str, str]:
    login_data = {"username": superuser.email, "password": "password123"}
    r = await async_client.post("/api/v1/login/", data=login_data)
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_system(transactional_session: AsyncSession) -> System:
    kind = SystemKind(code="RDBMS_CRAWL_TEST", name="RDBMS for Crawl Test")
    flavor = SystemFlavor(
        code="PG_CRAWL_TEST", name="Postgres for Crawl Test", kind=kind
    )
    system = System(code="pg-crawl-test", name="PG Crawl Test", flavor=flavor)
    transactional_session.add_all([kind, flavor, system])
    await transactional_session.commit()
    await transactional_session.refresh(system)
    return system


@pytest_asyncio.fixture
async def test_crawl_run(
    transactional_session: AsyncSession, test_system: System
) -> CrawlRun:
    cr = CrawlRun(
        system_id=test_system.id,
        status="running",
        started_at=datetime.now(timezone.utc),
        config={"schemas": ["public"]},
    )
    transactional_session.add(cr)
    await transactional_session.commit()
    await transactional_session.refresh(cr)
    return cr


@pytest.mark.asyncio
class TestCrawlRunAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_crawl_run_success(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_system: System,
    ):
        data = {
            "system_id": str(test_system.id),
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "config": {"schemas": ["public", "analytics"]},
        }
        response = await async_client.post(
            "/api/v1/crawl-runs/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 201
        res_json = response.json()
        assert res_json["status"] == "running"
        assert res_json["system_id"] == str(test_system.id)
        assert res_json["config"] == {"schemas": ["public", "analytics"]}

    async def test_create_crawl_run_system_not_found(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
    ):
        data = {
            "system_id": str(uuid.uuid4()),
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "config": {},
        }
        response = await async_client.post(
            "/api/v1/crawl-runs/", json=data, headers=superuser_token_headers
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == errors.SYSTEM_NOT_FOUND

    async def test_get_crawl_run_by_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_crawl_run: CrawlRun,
    ):
        response = await async_client.get(
            f"/api/v1/crawl-runs/{test_crawl_run.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_crawl_run.id)

    async def test_get_all_crawl_runs_paginated(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_crawl_run: CrawlRun,
    ):
        response = await async_client.get(
            "/api/v1/crawl-runs/", headers=superuser_token_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    async def test_update_crawl_run_status(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_crawl_run: CrawlRun,
    ):
        update_data = {
            "status": "completed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "new_datasets": 5,
                "removed_datasets": 0,
                "new_fields": 23,
                "type_changes": 0,
            },
            "row_version": 1,
        }
        response = await async_client.put(
            f"/api/v1/crawl-runs/{test_crawl_run.id}",
            json=update_data,
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "completed"
        assert res_json["summary"]["new_datasets"] == 5

    async def test_filter_crawl_runs_by_system_id(
        self,
        async_client: AsyncClient,
        superuser_token_headers: dict,
        test_crawl_run: CrawlRun,
        test_system: System,
    ):
        response = await async_client.get(
            f"/api/v1/crawl-runs/?system_id={test_system.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["system_id"] == str(test_system.id)
```

- [ ] **Step 2: Run tests**

Run: `make test-docker`

Expected: All tests pass including new CrawlRun tests.

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_crawl_runs.py
git commit -m "test: add CrawlRun API tests"
```

---

### Task 8: Update Data Model Docs

**Files:**
- Modify: `docs/AIDE_data_model.json`

- [ ] **Step 1: Add CrawlRun table to ChartDB data model**

Read current `docs/AIDE_data_model.json`, then add the `crawl_runs` table entry with fields matching the model: `id`, `system_id`, `status`, `started_at`, `finished_at`, `config`, `summary`, `error_message`, plus mixin fields (`created_at`, `updated_at`, `created_by`, `updated_by`, `note`, `row_version`). Add relationship to `systems` table.

- [ ] **Step 2: Commit**

```bash
git add docs/AIDE_data_model.json
git commit -m "docs: add CrawlRun to data model diagram"
```

---

## Phase 2: Shared Schemas Package

Extracts Pydantic schemas from `backend/schemas/` into standalone `schemas/` package. Both `backend` and future `sdk` depend on `aide-schemas`.

---

### Task 9: Create `schemas/` Package Structure

**Files:**
- Create: `schemas/pyproject.toml`
- Create: `schemas/aide_schemas/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
# schemas/pyproject.toml
[project]
name = "aide-schemas"
version = "0.1.0"
description = "Shared Pydantic schemas for AIDE metastore"
requires-python = ">=3.13"
dependencies = [
    "pydantic>=2.0.0",
]
```

- [ ] **Step 2: Create empty `__init__.py`**

```python
# schemas/aide_schemas/__init__.py
```

- [ ] **Step 3: Commit**

```bash
git add schemas/
git commit -m "feat: scaffold aide-schemas package"
```

---

### Task 10: Move Pydantic Schemas to Shared Package

**Files:**
- Copy: All files from `backend/schemas/` to `schemas/aide_schemas/`
- Modify: Internal imports within copied files

This is a mechanical refactoring. For each file in `backend/schemas/`:

- [ ] **Step 1: Copy schema files**

Copy these files from `backend/schemas/` to `schemas/aide_schemas/`:
- `mixins.py`
- `pagination.py`
- `error.py`
- `system_kind.py`
- `system_flavor.py`
- `data_type.py`
- `credential_ref.py`
- `system.py`
- `dataset.py`
- `cast_rule.py`
- `field.py`
- `dataset_schema.py`
- `field_binding.py`
- `type_instance.py`
- `crawl_run.py`
- `user.py`

- [ ] **Step 2: Update internal imports**

In each copied file, change:
```python
from backend.schemas.mixins import ...
```
to:
```python
from aide_schemas.mixins import ...
```

- [ ] **Step 3: Create `__init__.py` with all exports**

Mirror `backend/schemas/__init__.py` but with `aide_schemas` imports:

```python
# schemas/aide_schemas/__init__.py
from .cast_rule import CastRuleCreate, CastRuleRead, CastRuleUpdate
from .credential_ref import CredentialRefCreate, CredentialRefRead, CredentialRefUpdate
from .crawl_run import CrawlRunCreate, CrawlRunRead, CrawlRunUpdate
from .data_type import DataTypeCreate, DataTypeRead, DataTypeUpdate
from .dataset import AnyDatasetCreate, AnyDatasetRead, AnyDatasetUpdate
from .dataset_schema import DatasetSchemaCreate, DatasetSchemaRead, DatasetSchemaUpdate
from .field import FieldCreate, FieldRead, FieldUpdate
from .field_binding import FieldBindingCreate, FieldBindingRead, FieldBindingUpdate
from .system_flavor import SystemFlavorCreate, SystemFlavorRead, SystemFlavorUpdate
from .system_kind import SystemKindCreate, SystemKindRead, SystemKindUpdate
from .system import SystemCreate, SystemRead, SystemUpdate
from .user import UserCreate, UserRead, UserUpdate
from .pagination import Page
from .mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin

# Re-export all
__all__ = [
    "CastRuleCreate", "CastRuleRead", "CastRuleUpdate",
    "CredentialRefCreate", "CredentialRefRead", "CredentialRefUpdate",
    "CrawlRunCreate", "CrawlRunRead", "CrawlRunUpdate",
    "DataTypeCreate", "DataTypeRead", "DataTypeUpdate",
    "AnyDatasetCreate", "AnyDatasetRead", "AnyDatasetUpdate",
    "DatasetSchemaCreate", "DatasetSchemaRead", "DatasetSchemaUpdate",
    "FieldCreate", "FieldRead", "FieldUpdate",
    "FieldBindingCreate", "FieldBindingRead", "FieldBindingUpdate",
    "SystemFlavorCreate", "SystemFlavorRead", "SystemFlavorUpdate",
    "SystemKindCreate", "SystemKindRead", "SystemKindUpdate",
    "SystemCreate", "SystemRead", "SystemUpdate",
    "UserCreate", "UserRead", "UserUpdate",
    "Page",
    "MetaDataMixin", "NoteMixin", "VersionedUpdateMixin",
]
```

- [ ] **Step 4: Commit**

```bash
git add schemas/
git commit -m "feat: populate aide-schemas with Pydantic models"
```

---

### Task 11: Update Backend to Depend on aide-schemas

**Files:**
- Modify: `pyproject.toml` (root)
- Modify: All `backend/schemas/*.py` files — replace implementations with re-exports
- Modify: `backend/schemas/__init__.py`

- [ ] **Step 1: Add aide-schemas as dependency**

In root `pyproject.toml`, add to dependencies:
```toml
"aide-schemas",
```

Add source configuration so uv resolves local package:
```toml
[tool.uv.sources]
aide-schemas = { path = "schemas", editable = true }
```

- [ ] **Step 2: Replace backend schema files with re-exports**

For each schema file in `backend/schemas/`, replace its content with re-exports from `aide_schemas`. Example for `backend/schemas/cast_rule.py`:

```python
# backend/schemas/cast_rule.py
from aide_schemas.cast_rule import (
    CastRuleCreate as CastRuleCreate,
    CastRuleRead as CastRuleRead,
    CastRuleUpdate as CastRuleUpdate,
    CastSafety as CastSafety,
)
```

Repeat for all schema files. The `backend/schemas/mixins.py` becomes:
```python
from aide_schemas.mixins import (
    UUIDMixin as UUIDMixin,
    TimestampMixin as TimestampMixin,
    UserTrackingMixin as UserTrackingMixin,
    NoteMixin as NoteMixin,
    VersionMixin as VersionMixin,
    VersionedUpdateMixin as VersionedUpdateMixin,
    MetaDataMixin as MetaDataMixin,
)
```

Keep `backend/schemas/filters.py` and `backend/schemas/error.py` in backend (they depend on FastAPI/backend-specific code — NOT shared).

- [ ] **Step 3: Run tests**

Run: `make test-docker`

Expected: All existing tests pass — imports are backward-compatible via re-exports.

- [ ] **Step 4: Run lint + format**

Run: `make check && make format`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml backend/schemas/ schemas/
git commit -m "refactor: backend schemas now re-export from aide-schemas"
```

---

## Phase 3: SDK Package

Async Python SDK wrapping the AIDE metastore REST API via httpx.

---

### Task 12: SDK Package Structure + Exceptions

**Files:**
- Create: `sdk/pyproject.toml`
- Create: `sdk/aide_sdk/__init__.py`
- Create: `sdk/aide_sdk/exceptions.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
# sdk/pyproject.toml
[project]
name = "aide-sdk"
version = "0.1.0"
description = "Python SDK for AIDE metastore REST API"
requires-python = ">=3.13"
dependencies = [
    "httpx>=0.27.0",
    "aide-schemas",
]

[tool.uv.sources]
aide-schemas = { path = "../schemas", editable = true }
```

- [ ] **Step 2: Create exceptions**

```python
# sdk/aide_sdk/exceptions.py
class AideApiError(Exception):
    def __init__(self, status_code: int, error_code: str, detail: str):
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        super().__init__(f"{error_code}: {detail}")


class NotFoundError(AideApiError):
    pass


class ConflictError(AideApiError):
    pass


class ValidationError(AideApiError):
    pass


class AuthError(AideApiError):
    pass


def raise_for_status(status_code: int, error_code: str, detail: str) -> None:
    if 200 <= status_code < 300:
        return
    cls = {
        401: AuthError,
        403: AuthError,
        404: NotFoundError,
        409: ConflictError,
        422: ValidationError,
    }.get(status_code, AideApiError)
    raise cls(status_code=status_code, error_code=error_code, detail=detail)
```

- [ ] **Step 3: Create `__init__.py`**

```python
# sdk/aide_sdk/__init__.py
from aide_sdk.exceptions import (
    AideApiError,
    AuthError,
    ConflictError,
    NotFoundError,
    ValidationError,
)

__all__ = [
    "AideApiError",
    "AuthError",
    "ConflictError",
    "NotFoundError",
    "ValidationError",
]
```

- [ ] **Step 4: Commit**

```bash
git add sdk/
git commit -m "feat: scaffold aide-sdk package with exceptions"
```

---

### Task 13: SDK Auth Module

**Files:**
- Create: `sdk/aide_sdk/auth.py`

- [ ] **Step 1: Create auth module**

```python
# sdk/aide_sdk/auth.py
from __future__ import annotations

import httpx


class TokenManager:
    def __init__(self, base_url: str, username: str, password: str):
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    async def get_access_token(self, client: httpx.AsyncClient) -> str:
        if self._access_token is None:
            await self._login(client)
        return self._access_token  # type: ignore[return-value]

    async def refresh(self, client: httpx.AsyncClient) -> str:
        if self._refresh_token is None:
            await self._login(client)
            return self._access_token  # type: ignore[return-value]

        response = await client.post(
            f"{self._base_url}/api/v1/login/refresh",
            json={"refresh_token": self._refresh_token},
        )
        if response.status_code == 200:
            data = response.json()
            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token", self._refresh_token)
            return self._access_token
        else:
            # Refresh failed, re-login
            await self._login(client)
            return self._access_token  # type: ignore[return-value]

    async def _login(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            f"{self._base_url}/api/v1/login/",
            data={"username": self._username, "password": self._password},
        )
        response.raise_for_status()
        data = response.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")

    def auth_headers(self) -> dict[str, str]:
        if self._access_token is None:
            return {}
        return {"Authorization": f"Bearer {self._access_token}"}
```

- [ ] **Step 2: Commit**

```bash
git add sdk/aide_sdk/auth.py
git commit -m "feat: add SDK auth/token manager"
```

---

### Task 14: SDK HTTP Client

**Files:**
- Create: `sdk/aide_sdk/client.py`

- [ ] **Step 1: Create the client**

```python
# sdk/aide_sdk/client.py
from __future__ import annotations

from typing import Any

import httpx

from aide_sdk.auth import TokenManager
from aide_sdk.exceptions import raise_for_status


class HttpClient:
    def __init__(self, base_url: str, token_manager: TokenManager):
        self._base_url = base_url.rstrip("/")
        self._token_manager = token_manager
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HttpClient:
        self._client = httpx.AsyncClient()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HttpClient not entered as context manager")
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        retry_on_401: bool = True,
    ) -> Any:
        url = f"{self._base_url}{path}"
        token = await self._token_manager.get_access_token(self.client)
        headers = {"Authorization": f"Bearer {token}"}

        response = await self.client.request(
            method, url, json=json, params=params, headers=headers
        )

        if response.status_code == 401 and retry_on_401:
            await self._token_manager.refresh(self.client)
            return await self._request(
                method, path, json=json, params=params, retry_on_401=False
            )

        if response.status_code >= 400:
            body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            raise_for_status(
                response.status_code,
                body.get("error_code", "UNKNOWN"),
                body.get("detail", response.text),
            )

        if response.status_code == 204:
            return None
        return response.json()

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, *, json: Any = None) -> Any:
        return await self._request("POST", path, json=json)

    async def put(self, path: str, *, json: Any = None) -> Any:
        return await self._request("PUT", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path)


class AideClient:
    def __init__(self, base_url: str, username: str, password: str):
        self._token_manager = TokenManager(base_url, username, password)
        self._http = HttpClient(base_url, self._token_manager)

    async def __aenter__(self) -> AideClient:
        await self._http.__aenter__()
        self._init_resources()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._http.__aexit__(*args)

    def _init_resources(self) -> None:
        from aide_sdk.resources.systems import SystemsResource
        from aide_sdk.resources.datasets import DatasetsResource
        from aide_sdk.resources.fields import FieldsResource
        from aide_sdk.resources.data_types import DataTypesResource
        from aide_sdk.resources.system_flavors import SystemFlavorsResource
        from aide_sdk.resources.dataset_schemas import DatasetSchemasResource
        from aide_sdk.resources.field_bindings import FieldBindingsResource
        from aide_sdk.resources.type_instances import TypeInstancesResource
        from aide_sdk.resources.crawl_runs import CrawlRunsResource

        self.systems = SystemsResource(self._http)
        self.datasets = DatasetsResource(self._http)
        self.fields = FieldsResource(self._http)
        self.data_types = DataTypesResource(self._http)
        self.system_flavors = SystemFlavorsResource(self._http)
        self.dataset_schemas = DatasetSchemasResource(self._http)
        self.field_bindings = FieldBindingsResource(self._http)
        self.type_instances = TypeInstancesResource(self._http)
        self.crawl_runs = CrawlRunsResource(self._http)
```

- [ ] **Step 2: Commit**

```bash
git add sdk/aide_sdk/client.py
git commit -m "feat: add SDK HTTP client with auto-retry on 401"
```

---

### Task 15: SDK Resource Base + All Entity Resources

**Files:**
- Create: `sdk/aide_sdk/resources/__init__.py`
- Create: `sdk/aide_sdk/resources/base.py`
- Create: `sdk/aide_sdk/resources/systems.py`
- Create: `sdk/aide_sdk/resources/datasets.py`
- Create: `sdk/aide_sdk/resources/fields.py`
- Create: `sdk/aide_sdk/resources/data_types.py`
- Create: `sdk/aide_sdk/resources/system_flavors.py`
- Create: `sdk/aide_sdk/resources/dataset_schemas.py`
- Create: `sdk/aide_sdk/resources/field_bindings.py`
- Create: `sdk/aide_sdk/resources/type_instances.py`
- Create: `sdk/aide_sdk/resources/crawl_runs.py`

- [ ] **Step 1: Create resource base class**

```python
# sdk/aide_sdk/resources/base.py
from __future__ import annotations

from typing import Any, Generic, Type, TypeVar
from uuid import UUID

from pydantic import BaseModel

from aide_sdk.client import HttpClient
from aide_schemas.pagination import Page

CreateT = TypeVar("CreateT", bound=BaseModel)
ReadT = TypeVar("ReadT", bound=BaseModel)
UpdateT = TypeVar("UpdateT", bound=BaseModel)


class BaseResource(Generic[CreateT, ReadT, UpdateT]):
    _path: str
    _read_schema: Type[ReadT]

    def __init__(self, http: HttpClient):
        self._http = http

    async def list(
        self,
        *,
        page: int = 1,
        size: int = 50,
        params: dict[str, Any] | None = None,
    ) -> Page[ReadT]:
        query = {"page": page, "size": size}
        if params:
            query.update(params)
        data = await self._http.get(self._path, params=query)
        return Page[self._read_schema].model_validate(data)  # type: ignore[name-defined]

    async def get(self, obj_id: UUID) -> ReadT:
        data = await self._http.get(f"{self._path}/{obj_id}")
        return self._read_schema.model_validate(data)

    async def create(self, obj_in: CreateT) -> ReadT:
        data = await self._http.post(
            self._path, json=obj_in.model_dump(mode="json")
        )
        return self._read_schema.model_validate(data)

    async def update(self, obj_id: UUID, obj_in: UpdateT) -> ReadT:
        data = await self._http.put(
            f"{self._path}/{obj_id}",
            json=obj_in.model_dump(mode="json", exclude_unset=True),
        )
        return self._read_schema.model_validate(data)

    async def delete(self, obj_id: UUID) -> ReadT:
        data = await self._http.delete(f"{self._path}/{obj_id}")
        return self._read_schema.model_validate(data)
```

- [ ] **Step 2: Create entity resources**

Each resource follows the same pattern. Example for systems:

```python
# sdk/aide_sdk/resources/systems.py
from aide_schemas.system import SystemCreate, SystemRead, SystemUpdate
from aide_sdk.resources.base import BaseResource


class SystemsResource(BaseResource[SystemCreate, SystemRead, SystemUpdate]):
    _path = "/api/v1/systems"
    _read_schema = SystemRead
```

```python
# sdk/aide_sdk/resources/datasets.py
from aide_schemas.dataset import AnyDatasetCreate, AnyDatasetRead, AnyDatasetUpdate
from aide_sdk.resources.base import BaseResource


class DatasetsResource(BaseResource[AnyDatasetCreate, AnyDatasetRead, AnyDatasetUpdate]):
    _path = "/api/v1/datasets"
    _read_schema = AnyDatasetRead
```

```python
# sdk/aide_sdk/resources/fields.py
from aide_schemas.field import FieldCreate, FieldRead, FieldUpdate
from aide_sdk.resources.base import BaseResource


class FieldsResource(BaseResource[FieldCreate, FieldRead, FieldUpdate]):
    _path = "/api/v1/fields"
    _read_schema = FieldRead
```

```python
# sdk/aide_sdk/resources/data_types.py
from aide_schemas.data_type import DataTypeCreate, DataTypeRead, DataTypeUpdate
from aide_sdk.resources.base import BaseResource


class DataTypesResource(BaseResource[DataTypeCreate, DataTypeRead, DataTypeUpdate]):
    _path = "/api/v1/data-types"
    _read_schema = DataTypeRead
```

```python
# sdk/aide_sdk/resources/system_flavors.py
from aide_schemas.system_flavor import SystemFlavorCreate, SystemFlavorRead, SystemFlavorUpdate
from aide_sdk.resources.base import BaseResource


class SystemFlavorsResource(BaseResource[SystemFlavorCreate, SystemFlavorRead, SystemFlavorUpdate]):
    _path = "/api/v1/system-flavors"
    _read_schema = SystemFlavorRead
```

```python
# sdk/aide_sdk/resources/dataset_schemas.py
from aide_schemas.dataset_schema import DatasetSchemaCreate, DatasetSchemaRead, DatasetSchemaUpdate
from aide_sdk.resources.base import BaseResource


class DatasetSchemasResource(BaseResource[DatasetSchemaCreate, DatasetSchemaRead, DatasetSchemaUpdate]):
    _path = "/api/v1/dataset-schemas"
    _read_schema = DatasetSchemaRead
```

```python
# sdk/aide_sdk/resources/field_bindings.py
from aide_schemas.field_binding import FieldBindingCreate, FieldBindingRead, FieldBindingUpdate
from aide_sdk.resources.base import BaseResource


class FieldBindingsResource(BaseResource[FieldBindingCreate, FieldBindingRead, FieldBindingUpdate]):
    _path = "/api/v1/field-bindings"
    _read_schema = FieldBindingRead
```

```python
# sdk/aide_sdk/resources/type_instances.py
from aide_schemas.type_instance import TypeInstanceCreate, TypeInstanceRead, TypeInstanceUpdate
from aide_sdk.resources.base import BaseResource


class TypeInstancesResource(BaseResource[TypeInstanceCreate, TypeInstanceRead, TypeInstanceUpdate]):
    _path = "/api/v1/type-instances"
    _read_schema = TypeInstanceRead
```

```python
# sdk/aide_sdk/resources/crawl_runs.py
from aide_schemas.crawl_run import CrawlRunCreate, CrawlRunRead, CrawlRunUpdate
from aide_sdk.resources.base import BaseResource


class CrawlRunsResource(BaseResource[CrawlRunCreate, CrawlRunRead, CrawlRunUpdate]):
    _path = "/api/v1/crawl-runs"
    _read_schema = CrawlRunRead

    async def delete(self, obj_id):
        raise NotImplementedError("CrawlRun deletion is not supported (audit log)")
```

```python
# sdk/aide_sdk/resources/__init__.py
```

- [ ] **Step 3: Update SDK `__init__.py`**

```python
# sdk/aide_sdk/__init__.py
from aide_sdk.client import AideClient
from aide_sdk.exceptions import (
    AideApiError,
    AuthError,
    ConflictError,
    NotFoundError,
    ValidationError,
)

__all__ = [
    "AideClient",
    "AideApiError",
    "AuthError",
    "ConflictError",
    "NotFoundError",
    "ValidationError",
]
```

- [ ] **Step 4: Commit**

```bash
git add sdk/
git commit -m "feat: add SDK resource base class and all entity resources"
```

---

### Task 16: SDK Tests

**Files:**
- Create: `sdk/tests/test_exceptions.py`
- Create: `sdk/tests/test_client.py`
- Create: `sdk/tests/conftest.py`

SDK tests use httpx mock or a test server. Lightweight unit tests for exception mapping and resource URL construction.

- [ ] **Step 1: Create test for exceptions**

```python
# sdk/tests/test_exceptions.py
import pytest
from aide_sdk.exceptions import (
    AuthError,
    ConflictError,
    NotFoundError,
    ValidationError,
    raise_for_status,
)


def test_raise_for_status_200_no_exception():
    raise_for_status(200, "OK", "success")


def test_raise_for_status_404_not_found():
    with pytest.raises(NotFoundError) as exc_info:
        raise_for_status(404, "NOT_FOUND", "not found")
    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "NOT_FOUND"


def test_raise_for_status_401_auth_error():
    with pytest.raises(AuthError):
        raise_for_status(401, "UNAUTHORIZED", "bad token")


def test_raise_for_status_409_conflict():
    with pytest.raises(ConflictError):
        raise_for_status(409, "VERSION_CONFLICT", "version mismatch")


def test_raise_for_status_422_validation():
    with pytest.raises(ValidationError):
        raise_for_status(422, "VALIDATION", "invalid input")
```

- [ ] **Step 2: Run SDK tests**

```bash
cd sdk && uv run pytest tests/ -v
```

- [ ] **Step 3: Commit**

```bash
git add sdk/tests/
git commit -m "test: add SDK exception unit tests"
```

---

## Phase 4: Crawler Package

CLI tool that inspects RDBMS via SQLAlchemy, normalizes metadata, diffs against metastore via SDK, and produces reports.

**CLI scope control:** `--tables` (include list, format `schema.table` or `table`) lets a user crawl a single table or subset. `--exclude-tables` removes specific tables. Filters composable with `--schemas` / `--exclude-schemas`. Example minimal test: `aide-crawler crawl --system-code X --tables public.users --format text`.

---

### Task 17: Crawler Package Structure + CLI Skeleton

**Files:**
- Create: `crawler/pyproject.toml`
- Create: `crawler/aide_crawler/__init__.py`
- Create: `crawler/aide_crawler/__main__.py`
- Create: `crawler/aide_crawler/cli.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
# crawler/pyproject.toml
[project]
name = "aide-crawler"
version = "0.1.0"
description = "RDBMS metadata crawler for AIDE metastore"
requires-python = ">=3.13"
dependencies = [
    "aide-sdk",
    "aide-schemas",
    "sqlalchemy>=2.0.44",
    "typer>=0.12.0",
    "pyyaml>=6.0",
]

[project.scripts]
aide-crawler = "aide_crawler.cli:app"

[tool.uv.sources]
aide-sdk = { path = "../sdk", editable = true }
aide-schemas = { path = "../schemas", editable = true }
```

- [ ] **Step 2: Create CLI skeleton**

```python
# crawler/aide_crawler/__init__.py
```

```python
# crawler/aide_crawler/__main__.py
from aide_crawler.cli import app

app()
```

```python
# crawler/aide_crawler/cli.py
from typing import Optional

import typer

app = typer.Typer(name="aide-crawler", help="AIDE metadata crawler")


@app.command()
def crawl(
    system_code: str = typer.Option(..., help="System code registered in metastore"),
    connection_url: Optional[str] = typer.Option(
        None,
        envvar="AIDE_CRAWLER_CONNECTION_URL",
        help="SQLAlchemy connection URL for target RDBMS",
    ),
    metastore_url: str = typer.Option(
        "http://localhost:8001",
        envvar="AIDE_METASTORE_URL",
        help="Metastore API base URL",
    ),
    metastore_user: str = typer.Option(
        ..., envvar="AIDE_METASTORE_USER", help="Metastore username"
    ),
    metastore_password: str = typer.Option(
        ..., envvar="AIDE_METASTORE_PASSWORD", help="Metastore password"
    ),
    schemas: Optional[str] = typer.Option(
        None, help="Comma-separated list of schemas to include"
    ),
    exclude_schemas: Optional[str] = typer.Option(
        None, help="Comma-separated list of schemas to exclude"
    ),
    tables: Optional[str] = typer.Option(
        None, help="Comma-separated list of tables to include (format: schema.table or table). If set, only these tables are crawled."
    ),
    exclude_tables: Optional[str] = typer.Option(
        None, help="Comma-separated list of tables to exclude"
    ),
    format: str = typer.Option("text", help="Output format: text or json"),
    output: Optional[str] = typer.Option(
        None, "-o", help="Output file path (default: stdout)"
    ),
):
    """Run full crawl pipeline: inspect -> normalize -> diff -> report."""
    import asyncio
    from aide_crawler.runner import run_crawl

    schema_list = schemas.split(",") if schemas else None
    exclude_schema_list = exclude_schemas.split(",") if exclude_schemas else None
    include_table_list = tables.split(",") if tables else None
    exclude_table_list = exclude_tables.split(",") if exclude_tables else None

    asyncio.run(
        run_crawl(
            system_code=system_code,
            connection_url=connection_url,
            metastore_url=metastore_url,
            metastore_user=metastore_user,
            metastore_password=metastore_password,
            include_schemas=schema_list,
            exclude_schemas=exclude_schema_list,
            include_tables=include_table_list,
            exclude_tables=exclude_table_list,
            output_format=format,
            output_file=output,
        )
    )


@app.command()
def inspect(
    connection_url: str = typer.Option(
        ...,
        envvar="AIDE_CRAWLER_CONNECTION_URL",
        help="SQLAlchemy connection URL for target RDBMS",
    ),
    schemas: Optional[str] = typer.Option(
        None, help="Comma-separated list of schemas to include"
    ),
    tables: Optional[str] = typer.Option(
        None, help="Comma-separated list of tables to include (format: schema.table or table)"
    ),
    format: str = typer.Option("text", help="Output format: text or json"),
):
    """Inspect only - output raw metadata, no metastore interaction."""
    import asyncio
    from aide_crawler.runner import run_inspect

    schema_list = schemas.split(",") if schemas else None
    table_list = tables.split(",") if tables else None
    asyncio.run(
        run_inspect(
            connection_url=connection_url,
            include_schemas=schema_list,
            include_tables=table_list,
            output_format=format,
        )
    )
```

- [ ] **Step 3: Commit**

```bash
git add crawler/
git commit -m "feat: scaffold aide-crawler package with CLI"
```

---

### Task 18: Inspector Module

**Files:**
- Create: `crawler/aide_crawler/inspector.py`

- [ ] **Step 1: Create the inspector**

```python
# crawler/aide_crawler/inspector.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, inspect


# Default system schemas to exclude per dialect
DEFAULT_EXCLUDE_SCHEMAS: dict[str, set[str]] = {
    "postgresql": {"information_schema", "pg_catalog", "pg_toast"},
    "mysql": {"information_schema", "mysql", "performance_schema", "sys"},
    "default": {"information_schema"},
}


@dataclass
class ColumnInfo:
    name: str
    type: Any  # SQLAlchemy type object
    nullable: bool
    default: str | None
    comment: str | None


@dataclass
class TableInfo:
    schema_name: str
    table_name: str
    is_view: bool
    columns: list[ColumnInfo]
    pk_columns: list[str]
    unique_constraints: list[dict[str, Any]]
    foreign_keys: list[dict[str, Any]]
    indexes: list[dict[str, Any]]
    comment: str | None


@dataclass
class InspectionResult:
    dialect_name: str
    database_name: str | None
    schemas: list[str]
    tables: list[TableInfo]


def run_inspection(
    connection_url: str,
    *,
    include_schemas: list[str] | None = None,
    exclude_schemas: list[str] | None = None,
    include_tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
) -> InspectionResult:
    """
    Connect to RDBMS and collect metadata via SQLAlchemy Inspector.
    Uses sync engine since inspect() does not support async.
    """
    engine = create_engine(connection_url)
    insp = inspect(engine)
    dialect_name = engine.dialect.name

    # Determine database name
    database_name: str | None = None
    url = engine.url
    if url.database:
        database_name = url.database

    # Determine schemas to inspect
    all_schemas = insp.get_schema_names()
    system_schemas = DEFAULT_EXCLUDE_SCHEMAS.get(
        dialect_name, DEFAULT_EXCLUDE_SCHEMAS["default"]
    )

    if include_schemas:
        target_schemas = [s for s in include_schemas if s in all_schemas]
    else:
        excluded = system_schemas | set(exclude_schemas or [])
        target_schemas = [s for s in all_schemas if s not in excluded]

    exclude_table_set = set(exclude_tables or [])

    # Build include_table_set. Accept "schema.table" or "table" format.
    # Entry matches if it equals table_name OR f"{schema}.{table_name}".
    include_table_set: set[str] | None = (
        set(include_tables) if include_tables else None
    )
    tables: list[TableInfo] = []

    def _should_include(schema: str, name: str) -> bool:
        if include_table_set is not None:
            qualified = f"{schema}.{name}"
            if name not in include_table_set and qualified not in include_table_set:
                return False
        if name in exclude_table_set or f"{schema}.{name}" in exclude_table_set:
            return False
        return True

    for schema in target_schemas:
        # Tables
        for table_name in insp.get_table_names(schema=schema):
            if not _should_include(schema, table_name):
                continue
            table_info = _inspect_table(
                insp, schema, table_name, is_view=False
            )
            tables.append(table_info)

        # Views
        for view_name in insp.get_view_names(schema=schema):
            if not _should_include(schema, view_name):
                continue
            table_info = _inspect_table(
                insp, schema, view_name, is_view=True
            )
            tables.append(table_info)

    engine.dispose()

    return InspectionResult(
        dialect_name=dialect_name,
        database_name=database_name,
        schemas=target_schemas,
        tables=tables,
    )


def _inspect_table(
    insp: Any,
    schema: str,
    table_name: str,
    *,
    is_view: bool,
) -> TableInfo:
    columns = []
    for col in insp.get_columns(table_name, schema=schema):
        columns.append(
            ColumnInfo(
                name=col["name"],
                type=col["type"],
                nullable=col.get("nullable", True),
                default=col.get("default"),
                comment=col.get("comment"),
            )
        )

    pk_constraint = insp.get_pk_constraint(table_name, schema=schema)
    pk_columns = pk_constraint.get("constrained_columns", []) if pk_constraint else []

    try:
        unique_constraints = insp.get_unique_constraints(table_name, schema=schema)
    except NotImplementedError:
        unique_constraints = []

    foreign_keys = insp.get_foreign_keys(table_name, schema=schema)
    indexes = insp.get_indexes(table_name, schema=schema)

    try:
        comment_info = insp.get_table_comment(table_name, schema=schema)
        comment = comment_info.get("text") if comment_info else None
    except NotImplementedError:
        comment = None

    return TableInfo(
        schema_name=schema,
        table_name=table_name,
        is_view=is_view,
        columns=columns,
        pk_columns=pk_columns,
        unique_constraints=[
            {"name": uc.get("name"), "columns": uc.get("column_names", [])}
            for uc in unique_constraints
        ],
        foreign_keys=[
            {
                "name": fk.get("name"),
                "constrained_columns": fk.get("constrained_columns", []),
                "referred_schema": fk.get("referred_schema"),
                "referred_table": fk.get("referred_table"),
                "referred_columns": fk.get("referred_columns", []),
            }
            for fk in foreign_keys
        ],
        indexes=[
            {
                "name": idx.get("name"),
                "columns": idx.get("column_names", []),
                "unique": idx.get("unique", False),
            }
            for idx in indexes
        ],
        comment=comment,
    )
```

- [ ] **Step 2: Commit**

```bash
git add crawler/aide_crawler/inspector.py
git commit -m "feat: add RDBMS inspector using SQLAlchemy inspect()"
```

---

### Task 19: Type Map Module

**Files:**
- Create: `crawler/aide_crawler/type_map.py`

- [ ] **Step 1: Create type mapping**

```python
# crawler/aide_crawler/type_map.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import types as sa_types

logger = logging.getLogger(__name__)


@dataclass
class TypeMapping:
    data_type_code: str
    type_params: dict[str, Any]


# Generic SQLAlchemy type -> DataType code mapping
# These codes must match DataType.code values pre-seeded in metastore
GENERIC_TYPE_MAP: dict[type, str] = {
    sa_types.BigInteger: "bigint",
    sa_types.Boolean: "boolean",
    sa_types.Date: "date",
    sa_types.DateTime: "timestamp",
    sa_types.Double: "double",
    sa_types.Float: "float",
    sa_types.Integer: "integer",
    sa_types.SmallInteger: "smallint",
    sa_types.String: "varchar",
    sa_types.Text: "text",
    sa_types.Time: "time",
    sa_types.Unicode: "varchar",
    sa_types.UnicodeText: "text",
    sa_types.Uuid: "uuid",
    sa_types.Numeric: "numeric",
    sa_types.LargeBinary: "bytea",
    sa_types.JSON: "json",
    sa_types.ARRAY: "array",
}

# Dialect-specific overrides: (dialect_name, type_class_name) -> code
DIALECT_TYPE_MAP: dict[tuple[str, str], str] = {
    ("postgresql", "JSONB"): "jsonb",
    ("postgresql", "UUID"): "uuid",
    ("postgresql", "INET"): "inet",
    ("postgresql", "CIDR"): "cidr",
    ("postgresql", "MACADDR"): "macaddr",
    ("postgresql", "INTERVAL"): "interval",
    ("postgresql", "TSVECTOR"): "tsvector",
    ("postgresql", "BYTEA"): "bytea",
    ("postgresql", "ENUM"): "enum",
    ("mysql", "TINYINT"): "tinyint",
    ("mysql", "MEDIUMINT"): "mediumint",
    ("mysql", "YEAR"): "year",
    ("mysql", "ENUM"): "enum",
    ("mysql", "SET"): "set",
}


def resolve_type(dialect_name: str, sa_type: Any) -> TypeMapping | None:
    """
    Map a SQLAlchemy type object to a DataType code and extracted parameters.
    Returns None if type is unknown.
    """
    type_class_name = type(sa_type).__name__

    # Try dialect-specific first
    code = DIALECT_TYPE_MAP.get((dialect_name, type_class_name))

    # Fallback to generic map
    if code is None:
        for sa_class, generic_code in GENERIC_TYPE_MAP.items():
            if isinstance(sa_type, sa_class):
                code = generic_code
                break

    if code is None:
        logger.warning(
            "Unknown SQL type: dialect=%s type=%s", dialect_name, type_class_name
        )
        return None

    # Extract parameters
    params: dict[str, Any] = {}
    if hasattr(sa_type, "length") and sa_type.length is not None:
        params["length"] = sa_type.length
    if hasattr(sa_type, "precision") and sa_type.precision is not None:
        params["precision"] = sa_type.precision
    if hasattr(sa_type, "scale") and sa_type.scale is not None:
        params["scale"] = sa_type.scale

    return TypeMapping(data_type_code=code, type_params=params)
```

- [ ] **Step 2: Commit**

```bash
git add crawler/aide_crawler/type_map.py
git commit -m "feat: add SQL type -> DataType code mapping"
```

---

### Task 20: Normalizer Module

**Files:**
- Create: `crawler/aide_crawler/normalizer.py`

- [ ] **Step 1: Create the normalizer**

```python
# crawler/aide_crawler/normalizer.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aide_crawler.inspector import InspectionResult, TableInfo, ColumnInfo
from aide_crawler.type_map import TypeMapping, resolve_type


@dataclass
class NormalizedField:
    name: str
    path: str
    type_mapping: TypeMapping | None


@dataclass
class NormalizedDataset:
    object_name: str
    catalog_name: str | None
    schema_name: str
    table_name: str
    is_view: bool
    pk_columns: list[str]
    uq_constraints: list[dict[str, Any]]
    comment: str | None
    fields: list[NormalizedField]
    indexes: list[dict[str, Any]]
    foreign_keys: list[dict[str, Any]]


@dataclass
class NormalizedResult:
    dialect_name: str
    datasets: list[NormalizedDataset]


def normalize(inspection: InspectionResult) -> NormalizedResult:
    """Map raw inspection output to normalized structures ready for SDK."""
    datasets: list[NormalizedDataset] = []

    for table in inspection.tables:
        object_name = f"{table.schema_name}.{table.table_name}"

        fields = []
        for col in table.columns:
            type_mapping = resolve_type(inspection.dialect_name, col.type)
            fields.append(
                NormalizedField(
                    name=col.name,
                    path=col.name,
                    type_mapping=type_mapping,
                )
            )

        datasets.append(
            NormalizedDataset(
                object_name=object_name,
                catalog_name=inspection.database_name,
                schema_name=table.schema_name,
                table_name=table.table_name,
                is_view=table.is_view,
                pk_columns=table.pk_columns,
                uq_constraints=table.unique_constraints,
                comment=table.comment,
                fields=fields,
                indexes=table.indexes,
                foreign_keys=table.foreign_keys,
            )
        )

    return NormalizedResult(
        dialect_name=inspection.dialect_name,
        datasets=datasets,
    )
```

- [ ] **Step 2: Commit**

```bash
git add crawler/aide_crawler/normalizer.py
git commit -m "feat: add metadata normalizer (Inspector output -> SDK models)"
```

---

### Task 21: Differ Module

**Files:**
- Create: `crawler/aide_crawler/differ.py`

- [ ] **Step 1: Create the differ**

```python
# crawler/aide_crawler/differ.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from aide_sdk import AideClient, NotFoundError
from aide_crawler.normalizer import NormalizedDataset, NormalizedField, NormalizedResult


@dataclass
class TypeChange:
    dataset_object_name: str
    field_name: str
    old_type: str
    new_type: str
    old_params: dict[str, Any]
    new_params: dict[str, Any]


@dataclass
class IndexChange:
    dataset_object_name: str
    index_name: str
    columns: list[str]
    is_unique: bool


@dataclass
class DiffResult:
    new_datasets: list[NormalizedDataset]
    removed_datasets: list[dict[str, Any]]  # DatasetRead as dicts
    new_fields: dict[str, list[NormalizedField]]  # keyed by object_name
    removed_fields: dict[str, list[dict[str, Any]]]  # keyed by object_name
    type_changes: list[TypeChange]
    new_indexes: dict[str, list[IndexChange]]
    removed_indexes: dict[str, list[IndexChange]]


async def compute_diff(
    client: AideClient,
    system_id: UUID,
    normalized: NormalizedResult,
) -> DiffResult:
    """Compare normalized crawl result against current metastore state."""

    # Fetch all existing datasets for this system
    existing_datasets: dict[str, dict[str, Any]] = {}
    page_num = 1
    while True:
        page = await client.datasets.list(
            page=page_num, size=100, params={"system_id": str(system_id)}
        )
        for item in page.items:
            ds = item.model_dump()
            existing_datasets[ds["object_name"]] = ds
        if page_num >= page.pages:
            break
        page_num += 1

    crawled_names = {d.object_name for d in normalized.datasets}
    existing_names = set(existing_datasets.keys())

    # New datasets
    new_datasets = [d for d in normalized.datasets if d.object_name not in existing_names]

    # Removed datasets
    removed_datasets = [
        existing_datasets[name]
        for name in existing_names - crawled_names
    ]

    # Compare fields for datasets that exist in both
    new_fields: dict[str, list[NormalizedField]] = {}
    removed_fields: dict[str, list[dict[str, Any]]] = {}
    type_changes: list[TypeChange] = []

    for nd in normalized.datasets:
        if nd.object_name not in existing_names:
            continue

        ds = existing_datasets[nd.object_name]
        ds_id = ds["id"]

        # Fetch existing fields
        existing_field_map: dict[str, dict[str, Any]] = {}
        fp = 1
        while True:
            fpage = await client.fields.list(
                page=fp, size=100, params={"dataset_id": str(ds_id)}
            )
            for f in fpage.items:
                fd = f.model_dump()
                existing_field_map[fd["name"]] = fd
            if fp >= fpage.pages:
                break
            fp += 1

        crawled_field_names = {f.name for f in nd.fields}
        existing_field_names = set(existing_field_map.keys())

        # New fields
        nf = [f for f in nd.fields if f.name not in existing_field_names]
        if nf:
            new_fields[nd.object_name] = nf

        # Removed fields
        rf = [
            existing_field_map[name]
            for name in existing_field_names - crawled_field_names
        ]
        if rf:
            removed_fields[nd.object_name] = rf

        # Type changes (compare type_mapping codes)
        for nfield in nd.fields:
            if nfield.name not in existing_field_names:
                continue
            if nfield.type_mapping is None:
                continue
            # Type comparison requires fetching FieldBinding + TypeInstance
            # For MVP, skip detailed type comparison — report new/removed fields only

    return DiffResult(
        new_datasets=new_datasets,
        removed_datasets=removed_datasets,
        new_fields=new_fields,
        removed_fields=removed_fields,
        type_changes=type_changes,
        new_indexes={},
        removed_indexes={},
    )
```

- [ ] **Step 2: Commit**

```bash
git add crawler/aide_crawler/differ.py
git commit -m "feat: add diff engine (crawled vs metastore state)"
```

---

### Task 22: Reporter Module

**Files:**
- Create: `crawler/aide_crawler/reporter.py`

- [ ] **Step 1: Create the reporter**

```python
# crawler/aide_crawler/reporter.py
from __future__ import annotations

import json
import sys
from typing import IO

from aide_crawler.differ import DiffResult


def report_text(diff: DiffResult, out: IO[str] = sys.stdout) -> None:
    """Human-readable diff report."""
    out.write("=== AIDE Crawler Diff Report ===\n\n")

    # New datasets
    if diff.new_datasets:
        out.write(f"--- New datasets ({len(diff.new_datasets)}) ---\n")
        for ds in diff.new_datasets:
            out.write(f"  + {ds.object_name}")
            if ds.is_view:
                out.write(" (view)")
            out.write(f"  [{len(ds.fields)} columns]\n")
        out.write("\n")

    # Removed datasets
    if diff.removed_datasets:
        out.write(f"--- Removed datasets ({len(diff.removed_datasets)}) ---\n")
        for ds in diff.removed_datasets:
            out.write(f"  - {ds['object_name']}\n")
        out.write("\n")

    # New fields
    if diff.new_fields:
        total = sum(len(v) for v in diff.new_fields.values())
        out.write(f"--- New fields ({total}) ---\n")
        for obj_name, fields in diff.new_fields.items():
            for f in fields:
                type_str = f.type_mapping.data_type_code if f.type_mapping else "unknown"
                out.write(f"  + {obj_name}.{f.name} ({type_str})\n")
        out.write("\n")

    # Removed fields
    if diff.removed_fields:
        total = sum(len(v) for v in diff.removed_fields.values())
        out.write(f"--- Removed fields ({total}) ---\n")
        for obj_name, fields in diff.removed_fields.items():
            for f in fields:
                out.write(f"  - {obj_name}.{f['name']}\n")
        out.write("\n")

    # Type changes
    if diff.type_changes:
        out.write(f"--- Type changes ({len(diff.type_changes)}) ---\n")
        for tc in diff.type_changes:
            out.write(
                f"  ~ {tc.dataset_object_name}.{tc.field_name}: "
                f"{tc.old_type} -> {tc.new_type}\n"
            )
        out.write("\n")

    # Summary
    out.write("--- Summary ---\n")
    out.write(f"  New datasets:     {len(diff.new_datasets)}\n")
    out.write(f"  Removed datasets: {len(diff.removed_datasets)}\n")
    out.write(f"  New fields:       {sum(len(v) for v in diff.new_fields.values())}\n")
    out.write(f"  Removed fields:   {sum(len(v) for v in diff.removed_fields.values())}\n")
    out.write(f"  Type changes:     {len(diff.type_changes)}\n")


def report_json(diff: DiffResult, out: IO[str] = sys.stdout) -> None:
    """Machine-readable JSON diff report."""
    data = {
        "new_datasets": [
            {"object_name": ds.object_name, "is_view": ds.is_view, "fields_count": len(ds.fields)}
            for ds in diff.new_datasets
        ],
        "removed_datasets": [
            {"object_name": ds["object_name"], "id": ds.get("id")}
            for ds in diff.removed_datasets
        ],
        "new_fields": {
            obj: [{"name": f.name, "type": f.type_mapping.data_type_code if f.type_mapping else None} for f in fields]
            for obj, fields in diff.new_fields.items()
        },
        "removed_fields": {
            obj: [{"name": f["name"]} for f in fields]
            for obj, fields in diff.removed_fields.items()
        },
        "type_changes": [
            {
                "dataset": tc.dataset_object_name,
                "field": tc.field_name,
                "old_type": tc.old_type,
                "new_type": tc.new_type,
            }
            for tc in diff.type_changes
        ],
        "summary": {
            "new_datasets": len(diff.new_datasets),
            "removed_datasets": len(diff.removed_datasets),
            "new_fields": sum(len(v) for v in diff.new_fields.values()),
            "removed_fields": sum(len(v) for v in diff.removed_fields.values()),
            "type_changes": len(diff.type_changes),
        },
    }
    json.dump(data, out, indent=2, default=str)
    out.write("\n")


def format_report(diff: DiffResult, fmt: str, out: IO[str] = sys.stdout) -> None:
    if fmt == "json":
        report_json(diff, out)
    else:
        report_text(diff, out)
```

- [ ] **Step 2: Commit**

```bash
git add crawler/aide_crawler/reporter.py
git commit -m "feat: add diff reporter (text + JSON output)"
```

---

### Task 23: Runner (Orchestrator)

**Files:**
- Create: `crawler/aide_crawler/runner.py`

- [ ] **Step 1: Create the runner**

```python
# crawler/aide_crawler/runner.py
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from aide_sdk import AideClient
from aide_schemas.crawl_run import CrawlRunCreate, CrawlRunUpdate

from aide_crawler.inspector import run_inspection, InspectionResult
from aide_crawler.normalizer import normalize
from aide_crawler.differ import compute_diff
from aide_crawler.reporter import format_report


async def run_crawl(
    *,
    system_code: str,
    connection_url: str | None,
    metastore_url: str,
    metastore_user: str,
    metastore_password: str,
    include_schemas: list[str] | None = None,
    exclude_schemas: list[str] | None = None,
    include_tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
    output_format: str = "text",
    output_file: str | None = None,
) -> None:
    if not connection_url:
        print("Error: --connection-url or AIDE_CRAWLER_CONNECTION_URL is required", file=sys.stderr)
        raise SystemExit(1)

    async with AideClient(
        base_url=metastore_url,
        username=metastore_user,
        password=metastore_password,
    ) as client:
        # Find system by code
        systems_page = await client.systems.list(params={"code": system_code})
        if not systems_page.items:
            print(f"Error: System '{system_code}' not found in metastore", file=sys.stderr)
            raise SystemExit(1)
        system = systems_page.items[0]
        system_id = system.id

        # Validate system has DataTypes seeded (via flavor)
        flavor_id = system.flavor_id
        dt_page = await client.data_types.list(params={"system_flavor_id": str(flavor_id)})
        if dt_page.total == 0:
            print(
                f"Error: No DataTypes found for system flavor. "
                f"Seed DataTypes before crawling.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        # Create CrawlRun
        crawl_config: dict[str, Any] = {
            "include_schemas": include_schemas,
            "exclude_schemas": exclude_schemas,
            "include_tables": include_tables,
            "exclude_tables": exclude_tables,
        }
        crawl_run = await client.crawl_runs.create(
            CrawlRunCreate(
                system_id=system_id,
                status="running",
                started_at=datetime.now(timezone.utc),
                config=crawl_config,
            )
        )

        try:
            # Inspect
            inspection = run_inspection(
                connection_url,
                include_schemas=include_schemas,
                exclude_schemas=exclude_schemas,
                include_tables=include_tables,
                exclude_tables=exclude_tables,
            )

            # Normalize
            normalized = normalize(inspection)

            # Diff
            diff = await compute_diff(client, system_id, normalized)

            # Report
            if output_file:
                with open(output_file, "w") as f:
                    format_report(diff, output_format, f)
                print(f"Report written to {output_file}", file=sys.stderr)
            else:
                format_report(diff, output_format)

            # Update CrawlRun as completed
            summary = {
                "new_datasets": len(diff.new_datasets),
                "removed_datasets": len(diff.removed_datasets),
                "new_fields": sum(len(v) for v in diff.new_fields.values()),
                "removed_fields": sum(len(v) for v in diff.removed_fields.values()),
                "type_changes": len(diff.type_changes),
            }
            await client.crawl_runs.update(
                crawl_run.id,
                CrawlRunUpdate(
                    status="completed",
                    finished_at=datetime.now(timezone.utc),
                    summary=summary,
                    row_version=crawl_run.row_version,
                ),
            )

        except Exception as exc:
            # Update CrawlRun as failed
            await client.crawl_runs.update(
                crawl_run.id,
                CrawlRunUpdate(
                    status="failed",
                    finished_at=datetime.now(timezone.utc),
                    error_message=str(exc),
                    row_version=crawl_run.row_version,
                ),
            )
            raise


async def run_inspect(
    *,
    connection_url: str,
    include_schemas: list[str] | None = None,
    include_tables: list[str] | None = None,
    output_format: str = "text",
) -> None:
    """Inspect-only mode: no metastore interaction."""
    inspection = run_inspection(
        connection_url,
        include_schemas=include_schemas,
        include_tables=include_tables,
    )

    if output_format == "json":
        data = {
            "dialect": inspection.dialect_name,
            "database": inspection.database_name,
            "schemas": inspection.schemas,
            "tables": [
                {
                    "schema": t.schema_name,
                    "table": t.table_name,
                    "is_view": t.is_view,
                    "columns": [
                        {
                            "name": c.name,
                            "type": str(c.type),
                            "nullable": c.nullable,
                        }
                        for c in t.columns
                    ],
                    "pk_columns": t.pk_columns,
                    "unique_constraints": t.unique_constraints,
                    "indexes": t.indexes,
                    "comment": t.comment,
                }
                for t in inspection.tables
            ],
        }
        print(json.dumps(data, indent=2, default=str))
    else:
        print(f"Dialect: {inspection.dialect_name}")
        print(f"Database: {inspection.database_name}")
        print(f"Schemas: {', '.join(inspection.schemas)}")
        print(f"Tables/Views: {len(inspection.tables)}")
        print()
        for t in inspection.tables:
            kind = "VIEW" if t.is_view else "TABLE"
            print(f"  {t.schema_name}.{t.table_name} ({kind}, {len(t.columns)} columns)")
            for c in t.columns:
                nullable = "NULL" if c.nullable else "NOT NULL"
                print(f"    {c.name}: {c.type} {nullable}")
```

- [ ] **Step 2: Commit**

```bash
git add crawler/aide_crawler/runner.py
git commit -m "feat: add crawler runner orchestrating full pipeline"
```

---

### Task 24: Crawler Unit Tests

**Files:**
- Create: `crawler/tests/test_type_map.py`
- Create: `crawler/tests/test_normalizer.py`
- Create: `crawler/tests/test_reporter.py`

- [ ] **Step 1: Type map tests**

```python
# crawler/tests/test_type_map.py
from sqlalchemy import types as sa_types
from aide_crawler.type_map import resolve_type


def test_resolve_varchar():
    result = resolve_type("postgresql", sa_types.String(length=255))
    assert result is not None
    assert result.data_type_code == "varchar"
    assert result.type_params == {"length": 255}


def test_resolve_numeric_with_precision_scale():
    result = resolve_type("postgresql", sa_types.Numeric(precision=10, scale=2))
    assert result is not None
    assert result.data_type_code == "numeric"
    assert result.type_params == {"precision": 10, "scale": 2}


def test_resolve_integer_no_params():
    result = resolve_type("postgresql", sa_types.Integer())
    assert result is not None
    assert result.data_type_code == "integer"
    assert result.type_params == {}


def test_resolve_boolean():
    result = resolve_type("postgresql", sa_types.Boolean())
    assert result is not None
    assert result.data_type_code == "boolean"


def test_resolve_unknown_type_returns_none():
    class CustomType(sa_types.TypeEngine):
        pass
    result = resolve_type("postgresql", CustomType())
    assert result is None
```

- [ ] **Step 2: Normalizer tests**

```python
# crawler/tests/test_normalizer.py
from sqlalchemy import types as sa_types
from aide_crawler.inspector import InspectionResult, TableInfo, ColumnInfo
from aide_crawler.normalizer import normalize


def test_normalize_single_table():
    inspection = InspectionResult(
        dialect_name="postgresql",
        database_name="testdb",
        schemas=["public"],
        tables=[
            TableInfo(
                schema_name="public",
                table_name="users",
                is_view=False,
                columns=[
                    ColumnInfo(name="id", type=sa_types.Integer(), nullable=False, default=None, comment=None),
                    ColumnInfo(name="name", type=sa_types.String(length=100), nullable=False, default=None, comment="User name"),
                ],
                pk_columns=["id"],
                unique_constraints=[],
                foreign_keys=[],
                indexes=[],
                comment="Users table",
            )
        ],
    )
    result = normalize(inspection)
    assert len(result.datasets) == 1
    ds = result.datasets[0]
    assert ds.object_name == "public.users"
    assert ds.catalog_name == "testdb"
    assert ds.schema_name == "public"
    assert ds.table_name == "users"
    assert ds.is_view is False
    assert ds.pk_columns == ["id"]
    assert len(ds.fields) == 2
    assert ds.fields[0].name == "id"
    assert ds.fields[0].type_mapping is not None
    assert ds.fields[0].type_mapping.data_type_code == "integer"


def test_normalize_view():
    inspection = InspectionResult(
        dialect_name="postgresql",
        database_name="testdb",
        schemas=["public"],
        tables=[
            TableInfo(
                schema_name="public",
                table_name="active_users",
                is_view=True,
                columns=[
                    ColumnInfo(name="id", type=sa_types.Integer(), nullable=False, default=None, comment=None),
                ],
                pk_columns=[],
                unique_constraints=[],
                foreign_keys=[],
                indexes=[],
                comment=None,
            )
        ],
    )
    result = normalize(inspection)
    assert result.datasets[0].is_view is True
```

- [ ] **Step 3: Reporter tests**

```python
# crawler/tests/test_reporter.py
import io

from aide_crawler.differ import DiffResult
from aide_crawler.normalizer import NormalizedDataset, NormalizedField
from aide_crawler.type_map import TypeMapping
from aide_crawler.reporter import format_report


def _make_diff() -> DiffResult:
    return DiffResult(
        new_datasets=[
            NormalizedDataset(
                object_name="public.orders",
                catalog_name="testdb",
                schema_name="public",
                table_name="orders",
                is_view=False,
                pk_columns=["id"],
                uq_constraints=[],
                comment=None,
                fields=[
                    NormalizedField(name="id", path="id", type_mapping=TypeMapping("integer", {})),
                    NormalizedField(name="total", path="total", type_mapping=TypeMapping("numeric", {"precision": 10, "scale": 2})),
                ],
                indexes=[],
                foreign_keys=[],
            )
        ],
        removed_datasets=[{"object_name": "public.legacy_orders", "id": "some-uuid"}],
        new_fields={},
        removed_fields={},
        type_changes=[],
        new_indexes={},
        removed_indexes={},
    )


def test_report_text():
    buf = io.StringIO()
    format_report(_make_diff(), "text", buf)
    output = buf.getvalue()
    assert "New datasets (1)" in output
    assert "public.orders" in output
    assert "Removed datasets (1)" in output
    assert "public.legacy_orders" in output


def test_report_json():
    import json
    buf = io.StringIO()
    format_report(_make_diff(), "json", buf)
    data = json.loads(buf.getvalue())
    assert data["summary"]["new_datasets"] == 1
    assert data["summary"]["removed_datasets"] == 1
```

- [ ] **Step 4: Run crawler tests**

```bash
cd crawler && uv run pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add crawler/tests/
git commit -m "test: add crawler unit tests (type_map, normalizer, reporter)"
```

---

### Task 25: Root pyproject.toml — Add SDK and Crawler Source References

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add source references for all local packages**

```toml
[tool.uv.sources]
aide-schemas = { path = "schemas", editable = true }
aide-sdk = { path = "sdk", editable = true }
aide-crawler = { path = "crawler", editable = true }
```

- [ ] **Step 2: Run format and check**

Run: `make format && make check`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add local package source references to root pyproject.toml"
```

---

### Task 26: Final Verification

- [ ] **Step 1: Run all backend tests**

Run: `make test-docker`

Expected: All existing + new CrawlRun tests pass.

- [ ] **Step 2: Run SDK tests**

```bash
cd sdk && uv run pytest tests/ -v
```

- [ ] **Step 3: Run crawler tests**

```bash
cd crawler && uv run pytest tests/ -v
```

- [ ] **Step 4: Verify CLI help works**

```bash
cd crawler && uv run aide-crawler --help
cd crawler && uv run aide-crawler crawl --help
cd crawler && uv run aide-crawler inspect --help
```

- [ ] **Step 5: Commit any remaining fixes**
