# Field Classifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `pii_tags` from `Field` into a new append-only `field_classifications` resource with its own audit history.

**Architecture:** New `FieldClassification` table with `MetaDataMixin` and NOT NULL `pii_tags TEXT[]`. Writes are append-only via `POST`; corrections are new rows. "Current" classification = latest row per `field_id` by `created_at`. Reads cover single-field current, full history, and batch-by-dataset. CRUD router extended with `supports_update`/`supports_delete` flags to skip PUT/DELETE for append-only resources. SDK mirrors the new shape.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, Alembic, pytest + pytest-asyncio, aide-sdk (httpx), Python 3.13, `uv` package manager, Docker for test DB.

**Reference spec:** `docs/superpowers/specs/2026-04-17-field-classifications-design.md`

**Conventions (from `CLAUDE.md`):**
- Backend tests run via `PYTEST_ARGS="-v tests/path/..." make test-docker`
- Format after changes: `make format`; lint/typecheck: `make check`
- Alembic: `make alembic-gen` (autogenerate) → review → `make alembic-head` (apply)
- SDK tests run locally: `cd sdk && uv run pytest tests/`
- After changing Python deps or adding a local workspace package, rebuild test image: `docker compose build test`
- Only one `aide-db-test-1` container at a time (port 5433); `docker stop aide-db-test-1` if already running from another worktree
- Enum-like string columns use `str, enum.Enum` + Pydantic validation; no native PG enum
- Update `docs/AIDE_data_model.json` when ORM changes
- Use Caveman commits (`caveman:caveman-commit` skill) — Conventional Commits, ≤50 char subject, no AI attribution trailers

---

## File Structure

**Backend — create:**
- `backend/models/field_classification.py` — SQLAlchemy model
- `backend/repositories/field_classification.py` — custom queries (`get_current`, `list_by_field`, `list_current_by_dataset`)
- `backend/services/field_classification.py` — create-only service with `field_id` validation
- `backend/api/v1/field_classifications.py` — router (CRUD subset + 2 custom endpoints)
- `backend/schemas/field_classification.py` — re-export shim
- `schemas/aide_schemas/field_classification.py` — Pydantic DTOs
- `backend/alembic/versions/<hash>_add_field_classifications.py` — single migration

**Backend — modify:**
- `backend/models/field.py` — drop `pii_tags` column
- `backend/models/__init__.py` — register `FieldClassification`
- `backend/services/__init__.py` — register `FieldClassificationService`
- `backend/schemas/__init__.py` — re-export new schemas
- `backend/schemas/filters.py` — add `FieldClassificationFilter` + sortable set
- `backend/api/v1/utils/crud_router.py` — add `supports_update`, `supports_delete` flags; make `update_schema` optional when update disabled
- `backend/core/errors.py` — add `FIELD_CLASSIFICATION_NOT_FOUND`
- `backend/db/uow.py` — register `field_classifications` repo
- `backend/main.py` — register router at `/api/v1/field-classifications`
- `schemas/aide_schemas/field.py` — drop `pii_tags` from `FieldBase`, `FieldUpdate`, `FieldTree`
- `schemas/aide_schemas/__init__.py` — export new schemas
- `tests/api/test_fields.py` — drop `pii_tags` assertions
- `tests/conftest.py` — no change expected, verify Field fixture needs no pii_tags
- `docs/AIDE_data_model.json` — drop `f_fld_pii_tags`, add `field_classifications` table + FK

**Backend — tests to create:**
- `tests/models/test_field_classification_model.py` — cascade delete
- `tests/repositories/test_field_classification_repository.py` — custom query behavior
- `tests/services/test_field_classification_service.py` — mocked UoW, `field_id` validation
- `tests/api/test_field_classifications.py` — full API surface + 405 on update/delete

**SDK — create:**
- `sdk/aide_sdk/resources/field_classifications.py` — resource with standard CRUD subset + custom methods
- `sdk/tests/test_field_classifications_resource.py` — (basic smoke tests, if patterns exist; otherwise skip per existing SDK test coverage)

**SDK — modify:**
- `sdk/aide_sdk/client.py` — register `FieldClassificationsResource`

---

## Task 1: Add `FieldClassification` Pydantic DTOs in `aide-schemas`

**Files:**
- Create: `schemas/aide_schemas/field_classification.py`
- Modify: `schemas/aide_schemas/__init__.py`

No test in this task — DTOs are exercised by API/SDK tests later. This is a pure definition step.

- [ ] **Step 1: Create DTO module**

Create `schemas/aide_schemas/field_classification.py` with this content:

```python
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin


class FieldClassificationBase(BaseModel):
    """Base field classification schema."""

    field_id: uuid.UUID
    pii_tags: list[str]
    reason: str | None = None


class FieldClassificationCreate(FieldClassificationBase, NoteMixin):
    """Schema for creating a classification entry. Append-only: every POST is a new row."""

    pass


class FieldClassificationRead(FieldClassificationBase, MetaDataMixin):
    """Schema for reading a classification row."""

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: Export from `aide_schemas.__init__`**

Edit `schemas/aide_schemas/__init__.py`. Add the import and `__all__` entries. Before:

```python
from .field_binding import FieldBindingCreate, FieldBindingRead, FieldBindingUpdate
```

Add after that line:

```python
from .field_classification import FieldClassificationCreate, FieldClassificationRead
```

And in `__all__`, after `"FieldBindingUpdate"`, add:

```python
    "FieldClassificationCreate",
    "FieldClassificationRead",
```

- [ ] **Step 3: Verify imports work**

Run: `cd schemas && uv run python -c "from aide_schemas import FieldClassificationCreate, FieldClassificationRead; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add schemas/aide_schemas/field_classification.py schemas/aide_schemas/__init__.py
git commit -m "feat(schemas): add FieldClassification DTOs"
```

---

## Task 2: Backend re-export for `FieldClassification` schemas

**Files:**
- Create: `backend/schemas/field_classification.py`
- Modify: `backend/schemas/__init__.py` (if it exports specific schemas — check first)

- [ ] **Step 1: Create re-export file**

Create `backend/schemas/field_classification.py`:

```python
from aide_schemas.field_classification import (
    FieldClassificationCreate as FieldClassificationCreate,
    FieldClassificationRead as FieldClassificationRead,
)
```

- [ ] **Step 2: Add to `backend/schemas/__init__.py`**

Edit `backend/schemas/__init__.py`. After the `from .field_binding import (...)` block, add:

```python
from .field_classification import (
    FieldClassificationCreate,
    FieldClassificationRead,
)
```

Then in `__all__`, after `"FieldBindingUpdate"`, append:

```python
    "FieldClassificationCreate",
    "FieldClassificationRead",
```

- [ ] **Step 3: Commit**

```bash
git add backend/schemas/field_classification.py backend/schemas/__init__.py
git commit -m "feat(schemas): re-export FieldClassification"
```

---

## Task 3: Remove `pii_tags` from `Field` ORM + Pydantic

**Files:**
- Modify: `backend/models/field.py`
- Modify: `schemas/aide_schemas/field.py`
- Modify: `tests/api/test_fields.py`

This task is a pure deletion. No new failing test — we're removing behaviour; existing tests will fail unless updated.

- [ ] **Step 1: Drop `pii_tags` from the ORM model**

Edit `backend/models/field.py`. Remove line 28:

```python
    pii_tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
```

Also remove `ARRAY` from imports if unused after the change.

- [ ] **Step 2: Drop `pii_tags` from Pydantic schemas**

Edit `schemas/aide_schemas/field.py`. Remove the three `pii_tags` lines in `FieldBase`, `FieldUpdate`, and `FieldTree` (lines 18, 35, 54 at time of writing).

Resulting `FieldBase` should be:

```python
class FieldBase(BaseModel):
    """Base field schema."""

    dataset_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    name: str
    path: str | None = None
    extra: dict[str, Any] | None = None
```

Analogous removal in `FieldUpdate` and `FieldTree`.

- [ ] **Step 3: Clean `tests/api/test_fields.py` of `pii_tags` references**

Edit `tests/api/test_fields.py`. Remove the two `pii_tags` lines (currently at 128 and 158), and the assertion at 166:

```python
assert res_json["pii_tags"] == ["email_address"]
```

- [ ] **Step 4: Run test suite to confirm no stale references**

Run: `PYTEST_ARGS="-v tests/api/test_fields.py" make test-docker`
Expected: All pass. If anything fails on `pii_tags`, resolve by deletion.

- [ ] **Step 5: Commit**

```bash
git add backend/models/field.py schemas/aide_schemas/field.py tests/api/test_fields.py
git commit -m "refactor(field): drop pii_tags from Field"
```

---

## Task 4: Create `FieldClassification` ORM model

**Files:**
- Create: `backend/models/field_classification.py`
- Modify: `backend/models/__init__.py`
- Test: `tests/models/test_field_classification_model.py`

- [ ] **Step 1: Write failing test — cascade delete**

Create `tests/models/test_field_classification_model.py`:

```python
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    DatasetRdbms,
    Field,
    FieldClassification,
    System,
    SystemFlavor,
    SystemKind,
)


@pytest.mark.asyncio
async def test_cascade_delete_field_removes_classifications(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="KIND_FC_TEST", name="Kind FC Test")
    flavor = SystemFlavor(code="FL_FC_TEST", name="Flavor FC Test", kind=kind)
    system = System(code="SYS_FC_TEST", name="System FC Test", flavor=flavor)
    dataset = DatasetRdbms(
        system=system,
        object_name="customers_fc_test",
        schema_name="public",
        table_name="customers",
    )
    field = Field(dataset=dataset, name="email")
    transactional_session.add_all([kind, flavor, system, dataset, field])
    await transactional_session.flush()

    cls = FieldClassification(field_id=field.id, pii_tags=["email_address"])
    transactional_session.add(cls)
    await transactional_session.flush()

    # Delete the Field — classification row must go with it.
    await transactional_session.delete(field)
    await transactional_session.flush()

    result = await transactional_session.execute(
        select(FieldClassification).where(FieldClassification.field_id == field.id)
    )
    assert result.scalars().first() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_ARGS="-v tests/models/test_field_classification_model.py" make test-docker`
Expected: FAIL with `ImportError: cannot import name 'FieldClassification' from 'backend.models'`.

- [ ] **Step 3: Create the ORM model**

Create `backend/models/field_classification.py`:

```python
import uuid

from sqlalchemy import ForeignKey, Index, Text, desc
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class FieldClassification(Base, MetaDataMixin):
    __tablename__ = "field_classifications"

    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=False,
    )
    pii_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    field = relationship("Field")

    __table_args__ = (
        Index(
            "ix_field_classifications_field_id_created_at",
            "field_id",
            desc("created_at"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"FieldClassification(id={self.id}, field_id={self.field_id}, "
            f"pii_tags={self.pii_tags})"
        )
```

- [ ] **Step 4: Register model in `backend/models/__init__.py`**

Open `backend/models/__init__.py`. After the `from .field_binding import FieldBinding as FieldBinding` line, add:

```python
from .field_classification import FieldClassification as FieldClassification
```

Append `"FieldClassification"` to the `__all__` list (after `"FieldBinding"`).

- [ ] **Step 5: Run test again — still fails (no migration yet)**

Run: `PYTEST_ARGS="-v tests/models/test_field_classification_model.py" make test-docker`
Expected: FAIL with a DB error (`relation "field_classifications" does not exist`). This is correct — migration in next task.

- [ ] **Step 6: Commit**

```bash
git add backend/models/field_classification.py backend/models/__init__.py tests/models/test_field_classification_model.py
git commit -m "feat(models): add FieldClassification ORM"
```

---

## Task 5: Generate + apply Alembic migration

**Files:**
- Create: `backend/alembic/versions/<autogen>_add_field_classifications.py`

- [ ] **Step 1: Autogenerate migration**

Run: `make alembic-gen`

When prompted for a message (or via arg), use: `add_field_classifications`. Exact invocation depends on the Make target; if it doesn't take a message, after running, rename the generated file or edit its `revision` metadata only if it conflicts. Open the newest file under `backend/alembic/versions/`.

- [ ] **Step 2: Review + clean the generated migration**

Open the new migration file. It should contain:
- `op.drop_column('fields', 'pii_tags')`
- `op.create_table('field_classifications', ...)` with columns for id, field_id, pii_tags (ARRAY, NOT NULL), reason, note, row_version, created_at, updated_at, created_by, updated_by
- An index `ix_field_classifications_field_id_created_at` on `(field_id, created_at DESC)`
- A default index on `id`, `created_by`, `updated_by` if mixin conventions dictate (match existing migrations)

Strip any unrelated operations (nullability drift, index tweaks on other tables) — keep focused.

If the autogenerated index uses ascending `created_at`, manually change to DESC. The server expression form is `sa.text("created_at DESC")` inside `op.create_index`:

```python
op.create_index(
    "ix_field_classifications_field_id_created_at",
    "field_classifications",
    ["field_id", sa.text("created_at DESC")],
)
```

Also ensure `pii_tags` is `nullable=False` (autogen may infer from the model — verify).

- [ ] **Step 3: Apply migration**

Run: `make alembic-head`
Expected: migration applies cleanly.

- [ ] **Step 4: Rerun Task 4 test — should now pass**

Run: `PYTEST_ARGS="-v tests/models/test_field_classification_model.py" make test-docker`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat(alembic): add field_classifications; drop fields.pii_tags"
```

---

## Task 6: `FieldClassificationRepository` — `get_current`

**Files:**
- Create: `backend/repositories/field_classification.py`
- Test: `tests/repositories/test_field_classification_repository.py`

- [ ] **Step 1: Write failing tests — `get_current`**

Create `tests/repositories/test_field_classification_repository.py`:

```python
import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    DatasetRdbms,
    Field,
    FieldClassification,
    System,
    SystemFlavor,
    SystemKind,
)
from backend.repositories.field_classification import (
    FieldClassificationRepository,
)


async def _make_field(session: AsyncSession, *, code_suffix: str) -> Field:
    kind = SystemKind(code=f"KIND_FCR_{code_suffix}", name=f"Kind FCR {code_suffix}")
    flavor = SystemFlavor(
        code=f"FL_FCR_{code_suffix}", name=f"Flavor FCR {code_suffix}", kind=kind
    )
    system = System(
        code=f"SYS_FCR_{code_suffix}", name=f"System FCR {code_suffix}", flavor=flavor
    )
    dataset = DatasetRdbms(
        system=system,
        object_name=f"customers_fcr_{code_suffix}",
        schema_name="public",
        table_name="customers",
    )
    field = Field(dataset=dataset, name=f"email_{code_suffix}")
    session.add_all([kind, flavor, system, dataset, field])
    await session.flush()
    return field


@pytest.mark.asyncio
async def test_get_current_returns_latest_row(transactional_session: AsyncSession):
    field = await _make_field(transactional_session, code_suffix="A")
    repo = FieldClassificationRepository(transactional_session)

    first = FieldClassification(field_id=field.id, pii_tags=["email"])
    transactional_session.add(first)
    await transactional_session.flush()
    # A small sleep ensures created_at ordering distinct on fast systems.
    await asyncio.sleep(0.01)
    second = FieldClassification(field_id=field.id, pii_tags=["email", "phone"])
    transactional_session.add(second)
    await transactional_session.flush()

    current = await repo.get_current(field.id)
    assert current is not None
    assert current.id == second.id
    assert current.pii_tags == ["email", "phone"]


@pytest.mark.asyncio
async def test_get_current_returns_none_when_no_rows(
    transactional_session: AsyncSession,
):
    field = await _make_field(transactional_session, code_suffix="B")
    repo = FieldClassificationRepository(transactional_session)

    current = await repo.get_current(field.id)
    assert current is None
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTEST_ARGS="-v tests/repositories/test_field_classification_repository.py" make test-docker`
Expected: FAIL with `ModuleNotFoundError: backend.repositories.field_classification`.

- [ ] **Step 3: Create repository with `get_current`**

Create `backend/repositories/field_classification.py`:

```python
import uuid
from typing import Sequence

from sqlalchemy import select

from backend.models.field_classification import FieldClassification
from backend.repositories.base import BaseRepository


class FieldClassificationRepository(BaseRepository[FieldClassification]):
    model = FieldClassification

    async def get_current(self, field_id: uuid.UUID) -> FieldClassification | None:
        """Return the most recent classification for a field, or None."""
        stmt = (
            select(self.model)
            .where(self.model.field_id == field_id)
            .order_by(self.model.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
```

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/repositories/test_field_classification_repository.py::test_get_current_returns_latest_row tests/repositories/test_field_classification_repository.py::test_get_current_returns_none_when_no_rows" make test-docker`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/repositories/field_classification.py tests/repositories/test_field_classification_repository.py
git commit -m "feat(repo): FieldClassificationRepository.get_current"
```

---

## Task 7: `FieldClassificationRepository` — `list_by_field`

**Files:**
- Modify: `backend/repositories/field_classification.py`
- Modify: `tests/repositories/test_field_classification_repository.py`

- [ ] **Step 1: Add failing test**

Append to `tests/repositories/test_field_classification_repository.py`:

```python
@pytest.mark.asyncio
async def test_list_by_field_returns_history_desc(
    transactional_session: AsyncSession,
):
    field = await _make_field(transactional_session, code_suffix="C")
    repo = FieldClassificationRepository(transactional_session)

    first = FieldClassification(field_id=field.id, pii_tags=["email"])
    transactional_session.add(first)
    await transactional_session.flush()
    await asyncio.sleep(0.01)
    second = FieldClassification(field_id=field.id, pii_tags=["email", "phone"])
    transactional_session.add(second)
    await transactional_session.flush()

    rows = await repo.list_by_field(field.id)
    assert [r.id for r in rows] == [second.id, first.id]
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTEST_ARGS="-v tests/repositories/test_field_classification_repository.py::test_list_by_field_returns_history_desc" make test-docker`
Expected: FAIL with `AttributeError: 'FieldClassificationRepository' object has no attribute 'list_by_field'`.

- [ ] **Step 3: Implement**

Edit `backend/repositories/field_classification.py`. Add method inside the class:

```python
    async def list_by_field(self, field_id: uuid.UUID) -> Sequence[FieldClassification]:
        """Return all classifications for a field, newest first."""
        stmt = (
            select(self.model)
            .where(self.model.field_id == field_id)
            .order_by(self.model.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
```

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/repositories/test_field_classification_repository.py::test_list_by_field_returns_history_desc" make test-docker`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/repositories/field_classification.py tests/repositories/test_field_classification_repository.py
git commit -m "feat(repo): FieldClassificationRepository.list_by_field"
```

---

## Task 8: `FieldClassificationRepository` — `list_current_by_dataset`

**Files:**
- Modify: `backend/repositories/field_classification.py`
- Modify: `tests/repositories/test_field_classification_repository.py`

- [ ] **Step 1: Add failing test**

Append to `tests/repositories/test_field_classification_repository.py`:

```python
@pytest.mark.asyncio
async def test_list_current_by_dataset_returns_one_per_classified_field(
    transactional_session: AsyncSession,
):
    # Two fields in the same dataset; one has multiple classifications, one has none.
    kind = SystemKind(code="KIND_FCR_D", name="Kind FCR D")
    flavor = SystemFlavor(code="FL_FCR_D", name="Flavor FCR D", kind=kind)
    system = System(code="SYS_FCR_D", name="System FCR D", flavor=flavor)
    dataset = DatasetRdbms(
        system=system,
        object_name="customers_fcr_d",
        schema_name="public",
        table_name="customers",
    )
    email = Field(dataset=dataset, name="email_d")
    phone = Field(dataset=dataset, name="phone_d")
    transactional_session.add_all([kind, flavor, system, dataset, email, phone])
    await transactional_session.flush()

    c1 = FieldClassification(field_id=email.id, pii_tags=["email"])
    transactional_session.add(c1)
    await transactional_session.flush()
    await asyncio.sleep(0.01)
    c2 = FieldClassification(field_id=email.id, pii_tags=["email", "login"])
    transactional_session.add(c2)
    await transactional_session.flush()

    # Second dataset — make sure the filter excludes its rows.
    kind2 = SystemKind(code="KIND_FCR_D2", name="Kind FCR D2")
    flavor2 = SystemFlavor(code="FL_FCR_D2", name="Flavor FCR D2", kind=kind2)
    system2 = System(code="SYS_FCR_D2", name="System FCR D2", flavor=flavor2)
    dataset2 = DatasetRdbms(
        system=system2,
        object_name="customers_fcr_d2",
        schema_name="public",
        table_name="customers",
    )
    other_field = Field(dataset=dataset2, name="email_d2")
    transactional_session.add_all([kind2, flavor2, system2, dataset2, other_field])
    await transactional_session.flush()
    transactional_session.add(
        FieldClassification(field_id=other_field.id, pii_tags=["email"])
    )
    await transactional_session.flush()

    repo = FieldClassificationRepository(transactional_session)
    rows = await repo.list_current_by_dataset(dataset.id)
    assert len(rows) == 1
    assert rows[0].id == c2.id
    assert rows[0].field_id == email.id
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTEST_ARGS="-v tests/repositories/test_field_classification_repository.py::test_list_current_by_dataset_returns_one_per_classified_field" make test-docker`
Expected: FAIL with missing attribute.

- [ ] **Step 3: Implement**

Edit `backend/repositories/field_classification.py`. Add import and method:

At top of file, add import for `Field`:

```python
from backend.models.field import Field
```

Inside the class, append:

```python
    async def list_current_by_dataset(
        self, dataset_id: uuid.UUID
    ) -> Sequence[FieldClassification]:
        """For each field in the dataset with ≥1 classification, return the latest row."""
        # Subquery: latest created_at per field_id for fields in this dataset.
        latest_subq = (
            select(
                self.model.field_id,
                self.model.created_at.label("max_created_at"),
            )
            .join(Field, Field.id == self.model.field_id)
            .where(Field.dataset_id == dataset_id)
            .order_by(self.model.field_id, self.model.created_at.desc())
            .distinct(self.model.field_id)
            .subquery()
        )

        stmt = (
            select(self.model)
            .join(
                latest_subq,
                (self.model.field_id == latest_subq.c.field_id)
                & (self.model.created_at == latest_subq.c.max_created_at),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
```

(Uses `DISTINCT ON (field_id)` via SQLAlchemy's `.distinct(col)` on PG.)

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/repositories/test_field_classification_repository.py" make test-docker`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/repositories/field_classification.py tests/repositories/test_field_classification_repository.py
git commit -m "feat(repo): list_current_by_dataset"
```

---

## Task 9: `FIELD_CLASSIFICATION_NOT_FOUND` error code

**Files:**
- Modify: `backend/core/errors.py`

- [ ] **Step 1: Add constant**

Edit `backend/core/errors.py`. After line `CRAWL_RUN_NOT_FOUND = "CRAWL_RUN_NOT_FOUND"`, append:

```python
FIELD_CLASSIFICATION_NOT_FOUND = "FIELD_CLASSIFICATION_NOT_FOUND"
```

- [ ] **Step 2: Add to ERROR_MAP**

Still in `backend/core/errors.py`, find the `ERROR_MAP` dict. After the `CRAWL_RUN_NOT_FOUND` entry (or analogous), append:

```python
    FIELD_CLASSIFICATION_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested field classification was not found.",
    ),
```

- [ ] **Step 3: Verify import**

Run: `cd /Users/volojaninroman/Projects/AIDE/aide/.claude/worktrees/serene-yonath-b10bde && uv run python -c "from backend.core.errors import FIELD_CLASSIFICATION_NOT_FOUND, ERROR_MAP; assert FIELD_CLASSIFICATION_NOT_FOUND in ERROR_MAP; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/core/errors.py
git commit -m "feat(errors): add FIELD_CLASSIFICATION_NOT_FOUND"
```

---

## Task 10: `FieldClassificationFilter`

**Files:**
- Modify: `backend/schemas/filters.py`

- [ ] **Step 1: Add filter + sortable set**

Edit `backend/schemas/filters.py`. After the `FieldBindingFilter` block, append:

```python
# ── FieldClassification ──────────────────────────────────────────────────
class FieldClassificationFilter(BaseFilter):
    field_id: uuid.UUID | None = None
    dataset_id: uuid.UUID | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None


FIELD_CLASSIFICATION_SORTABLE = {"created_at", "updated_at"}
```

(`dataset_id` on the filter will need special handling in the repository's filter application — see Task 12 for service wiring. If the generic filter logic in `backend/api/filter_sort.py` does not natively join, we handle `dataset_id` in the router by pre-joining or by adding a dedicated service method. Simplest path: add `dataset_id` to the filter but override list handling in the service — noted in the next task.)

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from backend.schemas.filters import FieldClassificationFilter, FIELD_CLASSIFICATION_SORTABLE; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/schemas/filters.py
git commit -m "feat(filters): FieldClassificationFilter"
```

---

## Task 11: `FieldClassificationService` — `field_id` validation in create

**Files:**
- Create: `backend/services/field_classification.py`
- Modify: `backend/services/__init__.py`
- Test: `tests/services/test_field_classification_service.py`

- [ ] **Step 1: Write failing test — create with unknown field_id raises FIELD_NOT_FOUND**

Create `tests/services/test_field_classification_service.py`:

```python
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.schemas.field_classification import FieldClassificationCreate
from backend.services.field_classification import FieldClassificationService


class _MockRepository:
    def __init__(self) -> None:
        self.create: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()


class _MockFields:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.fields = _MockFields()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    return _MockUnitOfWork()


@pytest.mark.asyncio
async def test_create_fails_on_unknown_field(mock_uow: _MockUnitOfWork):
    mock_uow.fields.get.return_value = None
    service = FieldClassificationService()
    payload = FieldClassificationCreate(
        field_id=uuid.uuid4(), pii_tags=["email"]
    )

    with pytest.raises(AppException) as exc:
        await service.create(uow=mock_uow, obj_in=payload, creator_id=None)
    assert exc.value.error_code == errors.FIELD_NOT_FOUND
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTEST_ARGS="-v tests/services/test_field_classification_service.py" make test-docker`
Expected: FAIL with `ModuleNotFoundError: backend.services.field_classification`.

- [ ] **Step 3: Create the service**

Create `backend/services/field_classification.py`:

```python
import uuid

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.field_classification import FieldClassification
from backend.repositories.field_classification import (
    FieldClassificationRepository,
)
from backend.schemas.field_classification import (
    FieldClassificationCreate,
    FieldClassificationRead,
)
from backend.services.base import GenericService


class FieldClassificationService(
    GenericService[
        FieldClassification,
        FieldClassificationCreate,
        FieldClassificationCreate,  # type: ignore[type-arg]
        FieldClassificationRead,
    ]
):
    """
    Service for append-only field classification entries.

    Update/delete are not supported by design — the router does not register
    those endpoints.
    """

    def __init__(self) -> None:
        super().__init__(
            model=FieldClassification,
            repository=FieldClassificationRepository,
            read_schema=FieldClassificationRead,
            not_found_error_code=errors.FIELD_CLASSIFICATION_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: FieldClassificationCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        if not await uow.fields.get(obj_in.field_id):
            raise AppException(errors.FIELD_NOT_FOUND)
```

Note: The `UpdateSchemaType` generic slot expects a `BaseModel` subclass. Since we never call `update()` for this service, we reuse `FieldClassificationCreate` as a placeholder to satisfy the type parameter. The router won't expose PUT.

- [ ] **Step 4: Register in `backend/services/__init__.py`**

Open `backend/services/__init__.py`. After `from .field_binding import FieldBindingService`, add:

```python
from .field_classification import FieldClassificationService
```

Append `"FieldClassificationService"` to the `__all__` list (after `"FieldBindingService"`).

- [ ] **Step 5: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/services/test_field_classification_service.py" make test-docker`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/field_classification.py backend/services/__init__.py tests/services/test_field_classification_service.py
git commit -m "feat(service): FieldClassificationService w/ field_id validation"
```

---

## Task 12: Register repo in UoW

**Files:**
- Modify: `backend/db/uow.py`

- [ ] **Step 1: Add import + attribute**

Edit `backend/db/uow.py`. Add import next to the other repository imports:

```python
from backend.repositories.field_classification import (
    FieldClassificationRepository,
)
```

Inside `__aenter__`, after `self.field_bindings = FieldBindingRepository(self.session)`, add:

```python
        self.field_classifications = FieldClassificationRepository(self.session)
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from backend.db.uow import UnitOfWork; uow = UnitOfWork(); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/db/uow.py
git commit -m "feat(uow): register field_classifications repo"
```

---

## Task 13: Extend `create_crud_router` with `supports_update` / `supports_delete`

**Files:**
- Modify: `backend/api/v1/utils/crud_router.py`

- [ ] **Step 1: Add flag params; make update_schema optional**

Edit `backend/api/v1/utils/crud_router.py`.

1. Change the `update_schema` parameter to accept `None`:

```python
    update_schema: Type[UpdateSchemaType] | None,
```

2. Add two new keyword-only params (place after `supports_batch`):

```python
    supports_update: bool = True,
    supports_delete: bool = True,
```

3. Guard the PUT block (lines around 228–249). Wrap the `@router.put(...)` and its handler in:

```python
    if supports_update:
        if update_schema is None:
            raise ValueError(
                "update_schema is required when supports_update=True"
            )

        @router.put(
            "/{obj_id}",
            response_model=read_schema,  # type: ignore[valid-type]
            summary=f"Update a {entity_name}",
            dependencies=update_dependencies,
            responses={
                **build_error_responses(
                    *(update_error_codes or []), UNAUTHORIZED, FORBIDDEN
                ),
            },
        )
        async def update(
            obj_id: uuid.UUID,
            obj_in: update_schema,  # type: ignore[valid-type]
            service: ServiceType = Depends(service_dependency),
            uow: UnitOfWork = Depends(UnitOfWork),
            current_user: User = Depends(get_current_user),
        ) -> Any:
            updater_id = current_user.id
            return await service.update(
                uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=updater_id
            )
```

4. Guard the DELETE block identically:

```python
    if supports_delete:

        @router.delete(
            "/{obj_id}",
            response_model=read_schema,  # type: ignore[valid-type]
            summary=f"Delete a {entity_name}",
            dependencies=delete_dependencies,
            responses={
                **build_error_responses(
                    *(delete_error_codes or []), UNAUTHORIZED, FORBIDDEN
                ),
            },
        )
        async def delete(
            obj_id: uuid.UUID,
            service: ServiceType = Depends(service_dependency),
            uow: UnitOfWork = Depends(UnitOfWork),
            current_user: User = Depends(get_current_user),
        ) -> Any:
            return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)
```

- [ ] **Step 2: Run existing tests to ensure no regression**

Run: `PYTEST_ARGS="-v tests/api/" make test-docker`
Expected: All pass. Existing callers pass `update_schema=FieldUpdate` etc. — defaults keep behavior identical.

- [ ] **Step 3: Commit**

```bash
git add backend/api/v1/utils/crud_router.py
git commit -m "feat(crud): add supports_update/delete flags"
```

---

## Task 14: `field_classifications` router — create, get, list with `dataset_id` filter

**Files:**
- Create: `backend/api/v1/field_classifications.py`
- Modify: `backend/main.py`
- Test: `tests/api/test_field_classifications.py`

For the `dataset_id` filter, the generic `filter_sort` dependency cannot express a JOIN. Simplest path: handle `dataset_id` at the service layer by overriding `get_paginated` if `dataset_id` is in filters, or — cleaner — provide a custom list endpoint on the router that delegates to the repository. Keep the generic list for plain `field_id` / `created_at` filters and add a branch in the service.

Chosen approach: override `get_paginated` in `FieldClassificationService` to intercept `dataset_id` from the filter dict, resolve via the repo's `list_current_by_dataset` logic (adapted for pagination), and otherwise delegate to the parent. **Simpler MVP:** skip `dataset_id` in the generic list endpoint (document this limitation) — the batch-by-dataset use case is already covered by the dedicated endpoint in Task 16. Filtering list by `dataset_id` without the "latest per field" semantics is low value and adds complexity. Drop `dataset_id` from `FieldClassificationFilter` to keep the generic list simple.

- [ ] **Step 1: Adjust filter — drop `dataset_id`**

Edit `backend/schemas/filters.py`. Remove `dataset_id: uuid.UUID | None = None` from `FieldClassificationFilter`. Resulting filter:

```python
class FieldClassificationFilter(BaseFilter):
    field_id: uuid.UUID | None = None
    created_at__gte: datetime | None = None
    created_at__lte: datetime | None = None
```

- [ ] **Step 2: Update spec note**

Edit `docs/superpowers/specs/2026-04-17-field-classifications-design.md`. In the API section, remove `dataset_id?` from the `GET /field-classifications` query params (leave only `field_id?`, `created_at__gte?`, `created_at__lte?`, `sort`, `page`, `size`). In "dataset filter" bullet, replace with: "Cross-dataset filtering is not supported on the generic list endpoint; use `/by-dataset/{dataset_id}/current` for the batch-current pattern."

- [ ] **Step 3: Write failing test — create happy path + field-not-found**

Create `tests/api/test_field_classifications.py`:

```python
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.main import app
from backend.models import (
    DatasetRdbms,
    Field,
    System,
    SystemFlavor,
    SystemKind,
    User,
)


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="fc_super.user@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
        is_superuser=True,
    )
    transactional_session.add(user)
    await transactional_session.commit()
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
async def seeded_field(transactional_session: AsyncSession) -> Field:
    kind = SystemKind(code="KIND_FCAPI", name="Kind FC API")
    flavor = SystemFlavor(code="FL_FCAPI", name="Flavor FC API", kind=kind)
    system = System(code="SYS_FCAPI", name="System FC API", flavor=flavor)
    dataset = DatasetRdbms(
        system=system,
        object_name="customers_fcapi",
        schema_name="public",
        table_name="customers",
    )
    field = Field(dataset=dataset, name="email_api")
    transactional_session.add_all([kind, flavor, system, dataset, field])
    await transactional_session.commit()
    return field


@pytest.mark.asyncio
async def test_create_happy_path(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    payload = {"field_id": str(seeded_field.id), "pii_tags": ["email"]}
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json=payload,
        headers=superuser_token_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["field_id"] == str(seeded_field.id)
    assert body["pii_tags"] == ["email"]


@pytest.mark.asyncio
async def test_create_with_empty_pii_tags_is_valid(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    payload = {"field_id": str(seeded_field.id), "pii_tags": []}
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json=payload,
        headers=superuser_token_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["pii_tags"] == []


@pytest.mark.asyncio
async def test_create_missing_pii_tags_is_422(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    payload = {"field_id": str(seeded_field.id)}
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json=payload,
        headers=superuser_token_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_unknown_field_id_is_404(
    async_client: AsyncClient,
    superuser_token_headers: dict[str, str],
):
    payload = {"field_id": str(uuid.uuid4()), "pii_tags": ["email"]}
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json=payload,
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert r.json()["error_code"] == "FIELD_NOT_FOUND"
```

Also ensure `async_client` fixture exists in conftest — inspect `tests/conftest.py` if the test above fails due to missing fixture. If `async_client` is not globally defined, check `tests/api/test_fields.py` for the actual fixture name and pattern, and mirror it.

- [ ] **Step 4: Run — expect fail**

Run: `PYTEST_ARGS="-v tests/api/test_field_classifications.py" make test-docker`
Expected: FAIL (router not registered → 404 on all).

- [ ] **Step 5: Create router**

Create `backend/api/v1/field_classifications.py`:

```python
import uuid

from fastapi import APIRouter, Depends

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    FIELD_CLASSIFICATION_NOT_FOUND,
    FIELD_NOT_FOUND,
    FORBIDDEN,
    UNAUTHORIZED,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.schemas.field_classification import (
    FieldClassificationCreate,
    FieldClassificationRead,
)
from backend.schemas.filters import (
    FIELD_CLASSIFICATION_SORTABLE,
    FieldClassificationFilter,
)
from backend.services.field_classification import FieldClassificationService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=FieldClassificationService,
    create_schema=FieldClassificationCreate,
    update_schema=None,
    read_schema=FieldClassificationRead,
    entity_name="field classification",
    create_error_codes=[FIELD_NOT_FOUND],
    get_one_error_codes=[FIELD_CLASSIFICATION_NOT_FOUND],
    filter_model=FieldClassificationFilter,
    sortable_fields=FIELD_CLASSIFICATION_SORTABLE,
    default_sort="-created_at",
    supports_update=False,
    supports_delete=False,
)

router.include_router(crud_router)
```

(Custom endpoints for `/current/{field_id}` and `/by-dataset/{dataset_id}/current` added in later tasks.)

- [ ] **Step 6: Register in `main.py`**

Edit `backend/main.py`. Add near the other v1 imports:

```python
from backend.api.v1 import field_classifications as v1_field_classifications
```

And register the router alongside siblings:

```python
app.include_router(
    v1_field_classifications.router,
    prefix=f"{api_v1_prefix}/field-classifications",
    tags=["Field Classifications"],
)
```

- [ ] **Step 7: Run — expect create tests pass**

Run: `PYTEST_ARGS="-v tests/api/test_field_classifications.py::test_create_happy_path tests/api/test_field_classifications.py::test_create_with_empty_pii_tags_is_valid tests/api/test_field_classifications.py::test_create_missing_pii_tags_is_422 tests/api/test_field_classifications.py::test_create_unknown_field_id_is_404" make test-docker`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/api/v1/field_classifications.py backend/main.py backend/schemas/filters.py docs/superpowers/specs/2026-04-17-field-classifications-design.md tests/api/test_field_classifications.py
git commit -m "feat(api): field-classifications router (create/get/list)"
```

---

## Task 15: API — `/current/{field_id}` custom endpoint

**Files:**
- Modify: `backend/api/v1/field_classifications.py`
- Modify: `backend/services/field_classification.py`
- Modify: `tests/api/test_field_classifications.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/api/test_field_classifications.py`:

```python
@pytest.mark.asyncio
async def test_current_returns_latest(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    # Two posts; the /current endpoint must return the second.
    await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(seeded_field.id), "pii_tags": ["email"]},
        headers=superuser_token_headers,
    )
    r2 = await async_client.post(
        "/api/v1/field-classifications/",
        json={
            "field_id": str(seeded_field.id),
            "pii_tags": ["email", "login"],
        },
        headers=superuser_token_headers,
    )
    second_id = r2.json()["id"]

    r = await async_client.get(
        f"/api/v1/field-classifications/current/{seeded_field.id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == second_id


@pytest.mark.asyncio
async def test_current_404_when_unclassified(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    r = await async_client.get(
        f"/api/v1/field-classifications/current/{seeded_field.id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert r.json()["error_code"] == "FIELD_CLASSIFICATION_NOT_FOUND"
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTEST_ARGS="-v tests/api/test_field_classifications.py::test_current_returns_latest tests/api/test_field_classifications.py::test_current_404_when_unclassified" make test-docker`
Expected: FAIL (404 Not Found from FastAPI because route not registered, body likely missing error_code — tests assert specific `error_code`).

- [ ] **Step 3: Add service method**

Edit `backend/services/field_classification.py`. Add method inside the class:

```python
    async def get_current(
        self, uow: UnitOfWork, field_id: uuid.UUID
    ) -> FieldClassificationRead:
        async with uow:
            row = await uow.field_classifications.get_current(field_id)
            if row is None:
                raise AppException(errors.FIELD_CLASSIFICATION_NOT_FOUND)
            return FieldClassificationRead.model_validate(row)
```

Also add import at top of the service file:

```python
from backend.db.uow import UnitOfWork
```

(already present — verify)

- [ ] **Step 4: Add router endpoint**

Edit `backend/api/v1/field_classifications.py`. After `router.include_router(crud_router)`, append:

```python
@router.get(
    "/current/{field_id}",
    response_model=FieldClassificationRead,
    summary="Get the current classification for a field",
    responses={
        **build_error_responses(
            FIELD_CLASSIFICATION_NOT_FOUND, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def get_current_for_field(
    field_id: uuid.UUID,
    service: FieldClassificationService = Depends(FieldClassificationService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> FieldClassificationRead:
    return await service.get_current(uow=uow, field_id=field_id)
```

- [ ] **Step 5: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/api/test_field_classifications.py::test_current_returns_latest tests/api/test_field_classifications.py::test_current_404_when_unclassified" make test-docker`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/api/v1/field_classifications.py backend/services/field_classification.py tests/api/test_field_classifications.py
git commit -m "feat(api): current classification per field"
```

---

## Task 16: API — `/by-dataset/{dataset_id}/current` batch endpoint

**Files:**
- Modify: `backend/api/v1/field_classifications.py`
- Modify: `backend/services/field_classification.py`
- Modify: `tests/api/test_field_classifications.py`

- [ ] **Step 1: Append failing test**

Append to `tests/api/test_field_classifications.py`:

```python
@pytest.mark.asyncio
async def test_by_dataset_current_returns_one_per_classified_field(
    async_client: AsyncClient,
    transactional_session: AsyncSession,
    superuser_token_headers: dict[str, str],
):
    # Dataset with two fields; classify one only.
    kind = SystemKind(code="KIND_FCAPI_D", name="Kind FCAPI D")
    flavor = SystemFlavor(code="FL_FCAPI_D", name="Flavor FCAPI D", kind=kind)
    system = System(code="SYS_FCAPI_D", name="System FCAPI D", flavor=flavor)
    dataset = DatasetRdbms(
        system=system,
        object_name="customers_fcapi_d",
        schema_name="public",
        table_name="customers",
    )
    email = Field(dataset=dataset, name="email_fcapi_d")
    phone = Field(dataset=dataset, name="phone_fcapi_d")
    transactional_session.add_all([kind, flavor, system, dataset, email, phone])
    await transactional_session.commit()

    await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(email.id), "pii_tags": ["email"]},
        headers=superuser_token_headers,
    )
    r2 = await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(email.id), "pii_tags": ["email", "login"]},
        headers=superuser_token_headers,
    )
    latest_id = r2.json()["id"]

    r = await async_client.get(
        f"/api/v1/field-classifications/by-dataset/{dataset.id}/current",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["id"] == latest_id
    assert body[0]["field_id"] == str(email.id)
```

- [ ] **Step 2: Run — expect fail**

Run: `PYTEST_ARGS="-v tests/api/test_field_classifications.py::test_by_dataset_current_returns_one_per_classified_field" make test-docker`
Expected: FAIL (route not registered).

- [ ] **Step 3: Add service method**

Edit `backend/services/field_classification.py`. Add:

```python
    async def list_current_by_dataset(
        self, uow: UnitOfWork, dataset_id: uuid.UUID
    ) -> list[FieldClassificationRead]:
        async with uow:
            rows = await uow.field_classifications.list_current_by_dataset(
                dataset_id
            )
            return [FieldClassificationRead.model_validate(r) for r in rows]
```

- [ ] **Step 4: Add router endpoint**

Edit `backend/api/v1/field_classifications.py`. After the `/current/{field_id}` handler, append:

```python
@router.get(
    "/by-dataset/{dataset_id}/current",
    response_model=list[FieldClassificationRead],
    summary="List current classifications for all fields in a dataset",
    responses={
        **build_error_responses(UNAUTHORIZED, FORBIDDEN),
    },
)
async def list_current_by_dataset(
    dataset_id: uuid.UUID,
    service: FieldClassificationService = Depends(FieldClassificationService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> list[FieldClassificationRead]:
    return await service.list_current_by_dataset(uow=uow, dataset_id=dataset_id)
```

- [ ] **Step 5: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/api/test_field_classifications.py::test_by_dataset_current_returns_one_per_classified_field" make test-docker`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/api/v1/field_classifications.py backend/services/field_classification.py tests/api/test_field_classifications.py
git commit -m "feat(api): batch current-by-dataset"
```

---

## Task 17: Verify PUT/DELETE are not exposed (405)

**Files:**
- Modify: `tests/api/test_field_classifications.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/api/test_field_classifications.py`:

```python
@pytest.mark.asyncio
async def test_put_returns_405(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(seeded_field.id), "pii_tags": ["email"]},
        headers=superuser_token_headers,
    )
    obj_id = r.json()["id"]
    r2 = await async_client.put(
        f"/api/v1/field-classifications/{obj_id}",
        json={"pii_tags": ["email_address"]},
        headers=superuser_token_headers,
    )
    assert r2.status_code == 405


@pytest.mark.asyncio
async def test_delete_returns_405(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(seeded_field.id), "pii_tags": ["email"]},
        headers=superuser_token_headers,
    )
    obj_id = r.json()["id"]
    r2 = await async_client.delete(
        f"/api/v1/field-classifications/{obj_id}",
        headers=superuser_token_headers,
    )
    assert r2.status_code == 405
```

- [ ] **Step 2: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/api/test_field_classifications.py::test_put_returns_405 tests/api/test_field_classifications.py::test_delete_returns_405" make test-docker`
Expected: PASS (crud_router does not register PUT/DELETE per Task 13 flags).

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_field_classifications.py
git commit -m "test(api): PUT/DELETE return 405"
```

---

## Task 18: Get-one + list endpoints sanity

**Files:**
- Modify: `tests/api/test_field_classifications.py`

- [ ] **Step 1: Append failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_get_one_returns_row(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    r = await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(seeded_field.id), "pii_tags": ["email"]},
        headers=superuser_token_headers,
    )
    obj_id = r.json()["id"]

    r2 = await async_client.get(
        f"/api/v1/field-classifications/{obj_id}",
        headers=superuser_token_headers,
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == obj_id


@pytest.mark.asyncio
async def test_list_filters_by_field_id_sorted_desc(
    async_client: AsyncClient,
    seeded_field: Field,
    superuser_token_headers: dict[str, str],
):
    await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(seeded_field.id), "pii_tags": ["email"]},
        headers=superuser_token_headers,
    )
    r2 = await async_client.post(
        "/api/v1/field-classifications/",
        json={"field_id": str(seeded_field.id), "pii_tags": ["email", "login"]},
        headers=superuser_token_headers,
    )
    latest_id = r2.json()["id"]

    r = await async_client.get(
        "/api/v1/field-classifications/",
        params={"field_id": str(seeded_field.id), "sort": "-created_at"},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert items[0]["id"] == latest_id
```

- [ ] **Step 2: Run — expect pass (list + get already wired by crud_router)**

Run: `PYTEST_ARGS="-v tests/api/test_field_classifications.py::test_get_one_returns_row tests/api/test_field_classifications.py::test_list_filters_by_field_id_sorted_desc" make test-docker`
Expected: PASS. If list fails on sort param, verify `default_sort="-created_at"` in `create_crud_router` call and that the `FilterSortParams` dependency parses `sort`.

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_field_classifications.py
git commit -m "test(api): get-one + filtered list"
```

---

## Task 19: Run full backend test suite + format + check

**Files:** N/A (verification)

- [ ] **Step 1: Format + lint**

Run: `make format && make check`
Expected: No errors. If ruff flags unused `ARRAY` import in `backend/models/field.py` from Task 3, remove it. Pre-existing mypy errors in `backend/scripts/_seed_core.py` and `sdk/aide_sdk/resources/datasets.py` are known (per CLAUDE.md) and can be ignored.

- [ ] **Step 2: Run full backend tests**

Run: `make test-docker`
Expected: All pass.

- [ ] **Step 3: Commit any format-only changes**

```bash
git add -A
git status
# If there are format-only diffs:
git commit -m "style: format"
```

Skip if nothing changed.

---

## Task 20: Update `docs/AIDE_data_model.json`

**Files:**
- Modify: `docs/AIDE_data_model.json`

- [ ] **Step 1: Remove `pii_tags` field from the `fields` table entry**

Open `docs/AIDE_data_model.json`. Find the block near line 2211:

```json
{
  "id": "f_fld_pii_tags",
  "name": "pii_tags",
  ...
}
```

Delete the entire object (and the preceding comma if it's not the last in the array, or the trailing comma if it is).

- [ ] **Step 2: Add a new `field_classifications` table entry**

Mirror an existing append-only-style table block (e.g., a small one like `refresh_tokens` or a similar leaf). The new table needs:

- `id: "t_field_classifications"` (or matching convention)
- `name: "field_classifications"`
- Fields: `id`, `field_id` (FK → `fields.id`), `pii_tags` (ARRAY text, NOT NULL), `reason` (text), `note` (text), `row_version` (int), `created_at`, `updated_at`, `created_by` (FK → users), `updated_by` (FK → users)
- An index on `(field_id, created_at DESC)`

If the JSON format is verbose, copy a comparable table's block and adjust ids/types. Verify valid JSON with `python -m json.tool < docs/AIDE_data_model.json > /dev/null`.

- [ ] **Step 3: Add relationship (FK) entry**

Find the `relationships` section (or equivalent). Add one entry linking `field_classifications.field_id` → `fields.id` with `ON DELETE CASCADE`.

- [ ] **Step 4: Validate JSON**

Run: `python -m json.tool docs/AIDE_data_model.json > /dev/null && echo ok`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add docs/AIDE_data_model.json
git commit -m "docs: sync ER diagram for field_classifications"
```

---

## Task 21: SDK — `FieldClassificationsResource`

**Files:**
- Create: `sdk/aide_sdk/resources/field_classifications.py`
- Modify: `sdk/aide_sdk/client.py`

Use append-only-friendly base: inherit from `BaseResource` but override/omit `update` and `delete`. The cleanest approach is to subclass `BaseResource` and raise `NotImplementedError` on those methods, OR duplicate the relevant methods without inheriting from `BaseResource`. For minimal surface: subclass and shadow.

- [ ] **Step 1: Create resource**

Create `sdk/aide_sdk/resources/field_classifications.py`:

```python
from __future__ import annotations

from typing import List
from uuid import UUID

from pydantic import TypeAdapter

from aide_schemas.field_classification import (
    FieldClassificationCreate,
    FieldClassificationRead,
)
from aide_sdk.resources.base import BaseResource


class FieldClassificationsResource(
    BaseResource[FieldClassificationCreate, FieldClassificationRead, FieldClassificationCreate]
):
    """Append-only resource; update/delete raise NotImplementedError."""

    _path = "/api/v1/field-classifications"
    _read_schema = FieldClassificationRead

    async def update(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError("field_classifications is append-only")

    async def delete(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError("field_classifications is append-only")

    async def get_current(self, field_id: UUID) -> FieldClassificationRead:
        data = await self._http.get(f"{self._path}/current/{field_id}")
        return self._read_adapter.validate_python(data)

    async def list_history(
        self,
        field_id: UUID,
        *,
        page: int = 1,
        size: int = 50,
    ) -> List[FieldClassificationRead]:
        resp = await self.list(
            page=page, size=size, params={"field_id": str(field_id), "sort": "-created_at"}
        )
        return list(resp.items)

    async def list_current_by_dataset(
        self, dataset_id: UUID
    ) -> List[FieldClassificationRead]:
        data = await self._http.get(
            f"{self._path}/by-dataset/{dataset_id}/current"
        )
        adapter: TypeAdapter = TypeAdapter(List[FieldClassificationRead])
        return adapter.validate_python(data)
```

- [ ] **Step 2: Register in client**

Edit `sdk/aide_sdk/client.py`. Add import inside `_init_resources` alongside existing ones:

```python
        from aide_sdk.resources.field_classifications import (
            FieldClassificationsResource,
        )
```

And inside the method body:

```python
        self.field_classifications = FieldClassificationsResource(self._http)
```

- [ ] **Step 3: Verify SDK imports**

Run: `cd sdk && uv run python -c "from aide_sdk.resources.field_classifications import FieldClassificationsResource; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Run existing SDK tests to ensure no regression**

Run: `cd sdk && uv run pytest tests/ -v`
Expected: all existing tests pass. No new SDK tests in this plan — SDK tests currently cover only select resources (see `sdk/tests/`); adding a full test suite for `field_classifications` is out of scope here and can be a follow-up if the team wants parity.

- [ ] **Step 5: Commit**

```bash
git add sdk/aide_sdk/resources/field_classifications.py sdk/aide_sdk/client.py
git commit -m "feat(sdk): FieldClassificationsResource"
```

---

## Task 22: Final integration check

**Files:** N/A (verification)

- [ ] **Step 1: Rebuild test image (in case of SDK workspace changes)**

Run: `docker compose build test`
Expected: build succeeds. If SDK deps haven't changed this is a no-op but safe.

- [ ] **Step 2: Run full backend test suite**

Run: `make test-docker`
Expected: all pass.

- [ ] **Step 3: Run SDK tests**

Run: `cd sdk && uv run pytest tests/ -v`
Expected: all pass.

- [ ] **Step 4: Run crawler tests (sanity)**

Run: `cd crawler && uv run pytest tests/ -v`
Expected: all pass — crawler does not reference `pii_tags`.

- [ ] **Step 5: Final format + check**

Run: `make format && make check`
Expected: clean.

- [ ] **Step 6: Commit only if format changed anything**

```bash
git status
# If diff:
git add -A && git commit -m "style: post-merge format"
```

---

## Out of scope (follow-up)

- Updating `docs/superpowers/specs/2026-04-15-frontend-mantine-spa-design.md` and `docs/superpowers/plans/2026-04-15-frontend-roadmap.md` to use the new classifications resource (separate spec + plan).
- Crawler PII detector (writes to `field_classifications` directly).
- Steward UX endpoint (`POST /datasets/{id}/retag`) — deferred per spec.
- SDK tests for `FieldClassificationsResource` (can be added if/when the team adopts full SDK test coverage across resources).
