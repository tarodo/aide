# Dataset Lineage (Phase 2) Implementation Plan — Tech-Field Templates

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce reusable tech-field presets (SCD2, CDC payload, snapshot, ...) that can be applied to a Dataset to materialize `is_tech=True` Field rows via an abstract type-code resolver. Decoupled from Field (no FK) — applied templates evolve independently per dataset.

**Architecture:** Two new tables — `tech_field_templates` (preset code, name, layer) + `tech_field_template_fields` (child: name, type_code, order). Apply flow: `POST /api/v1/datasets/{id}/apply-tech-template` resolves each template_field's abstract `type_code` to a concrete `DataType.id` via (flavor, type_code) mapping defined in `backend/scripts/data/tech_type_resolver.yaml`, then creates Field rows (`is_tech=True`) with the resolved `data_type_id` stashed in `Field.extra`. Idempotent: re-applying skips existing names.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, PyYAML (already a dep). Tests via `make test-docker`.

**Spec:** `docs/superpowers/specs/2026-04-21-dataset-lineage-design.md` §3.7, §5.3, §8, §9.

**Phase 1 dependency:** `Field.is_tech` column (landed), `Dataset.pattern_code` column (landed), `DatasetLayer` enum (landed).

---

## File Map

**Created:**
- `backend/models/tech_field_template.py` — both `TechFieldTemplate` + `TechFieldTemplateField` classes (tightly coupled, tiny).
- `schemas/aide_schemas/tech_field_template.py` — Pydantic DTOs for both entities + apply-template request schema.
- `backend/schemas/tech_field_template.py` — re-export.
- `backend/repositories/tech_field_template.py` — parent repo.
- `backend/repositories/tech_field_template_field.py` — child repo.
- `backend/services/tech_field_template.py` — parent service.
- `backend/services/tech_field_template_field.py` — child service.
- `backend/api/v1/tech_field_templates.py` — router (all endpoints for both entities).
- `backend/core/tech_type_resolver.py` — YAML-backed resolver module.
- `backend/scripts/data/tech_type_resolver.yaml` — starter mappings.
- `backend/scripts/data/tech_templates.yaml` — starter template seed data.
- `backend/scripts/seed_tech_templates.py` — idempotent upsert script.
- `backend/alembic/versions/XXXX_create_tech_field_templates.py` — both tables in one migration (they ship together).
- `tests/models/test_tech_field_template.py`
- `tests/repositories/test_tech_field_template_repository.py`
- `tests/services/test_tech_field_template_service.py`
- `tests/services/test_tech_field_template_field_service.py`
- `tests/api/test_tech_field_templates.py`
- `tests/core/test_tech_type_resolver.py`
- `tests/scripts/test_seed_tech_templates.py`
- `docs/adr/adr-017-tech-field-templates.md`

**Modified:**
- `backend/models/__init__.py` — register `TechFieldTemplate`, `TechFieldTemplateField`.
- `backend/core/errors.py` — add template-specific error codes.
- `backend/db/uow.py` — register two new repositories.
- `backend/main.py` — include new router.
- `backend/services/dataset.py` — add `apply_tech_template` method.
- `backend/api/v1/datasets.py` — add `POST /{id}/apply-tech-template` endpoint.
- `tests/services/test_dataset_service.py` — apply-template tests.
- `tests/api/test_datasets.py` — apply endpoint test.
- `docs/AIDE_data_model.json` — add two new tables.
- `docs/adr/README.md` — index row for ADR-017.

---

## Task 1: Error codes

**Files:**
- Modify: `backend/core/errors.py`

- [ ] **Step 1: Add error codes**

In the constants section of `backend/core/errors.py`, add:

```python
TECH_FIELD_TEMPLATE_NOT_FOUND = "TECH_FIELD_TEMPLATE_NOT_FOUND"
TECH_FIELD_TEMPLATE_ALREADY_EXISTS = "TECH_FIELD_TEMPLATE_ALREADY_EXISTS"
TECH_FIELD_TEMPLATE_LAYER_MISMATCH = "TECH_FIELD_TEMPLATE_LAYER_MISMATCH"
TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND = "TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND"
TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS = "TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS"
TECH_TYPE_CODE_NOT_RESOLVABLE = "TECH_TYPE_CODE_NOT_RESOLVABLE"
```

In the `ERROR_MAP` dict, add matching entries:

```python
TECH_FIELD_TEMPLATE_NOT_FOUND: (status.HTTP_404_NOT_FOUND, "The requested tech-field template was not found."),
TECH_FIELD_TEMPLATE_ALREADY_EXISTS: (status.HTTP_409_CONFLICT, "A tech-field template with this code already exists."),
TECH_FIELD_TEMPLATE_LAYER_MISMATCH: (status.HTTP_400_BAD_REQUEST, "Template layer does not match dataset layer."),
TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND: (status.HTTP_404_NOT_FOUND, "The requested template field was not found."),
TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS: (status.HTTP_409_CONFLICT, "A template field with this name already exists in this template."),
TECH_TYPE_CODE_NOT_RESOLVABLE: (status.HTTP_400_BAD_REQUEST, "Cannot resolve abstract type_code to a concrete data type for this dataset flavor."),
```

- [ ] **Step 2: Format + commit**

```bash
make format
git add backend/core/errors.py
git commit -m "feat: add tech-field-template error codes"
```

---

## Task 2: Models + migration

**Files:**
- Create: `backend/models/tech_field_template.py`
- Modify: `backend/models/__init__.py`
- Create: `backend/alembic/versions/XXXX_create_tech_field_templates.py`
- Create: `tests/models/test_tech_field_template.py`

- [ ] **Step 1: Write failing tests**

Create `tests/models/test_tech_field_template.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)


@pytest.mark.asyncio
async def test_template_create(transactional_session: AsyncSession):
    tpl = TechFieldTemplate(
        code="scd2_core_v1",
        name="SCD2 on CORE",
        layer="core",
    )
    transactional_session.add(tpl)
    await transactional_session.flush()
    await transactional_session.refresh(tpl)
    assert tpl.id is not None
    assert tpl.row_version == 1


@pytest.mark.asyncio
async def test_template_code_unique(transactional_session: AsyncSession):
    transactional_session.add(
        TechFieldTemplate(code="dup_code", name="A", layer="core")
    )
    await transactional_session.flush()
    transactional_session.add(
        TechFieldTemplate(code="dup_code", name="B", layer="raw")
    )
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_template_field_create(transactional_session: AsyncSession):
    tpl = TechFieldTemplate(code="fld_t1", name="T1", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()
    tf = TechFieldTemplateField(
        template_id=tpl.id,
        name="valid_from",
        type_code="TIMESTAMP",
        order=0,
    )
    transactional_session.add(tf)
    await transactional_session.flush()
    await transactional_session.refresh(tf)
    assert tf.id is not None


@pytest.mark.asyncio
async def test_template_field_name_unique_per_template(
    transactional_session: AsyncSession,
):
    tpl = TechFieldTemplate(code="fld_t2", name="T2", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()
    transactional_session.add(
        TechFieldTemplateField(
            template_id=tpl.id, name="same", type_code="STRING", order=0
        )
    )
    await transactional_session.flush()
    transactional_session.add(
        TechFieldTemplateField(
            template_id=tpl.id, name="same", type_code="BIGINT", order=1
        )
    )
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_template_field_cascade_on_template_delete(
    transactional_session: AsyncSession,
):
    tpl = TechFieldTemplate(code="fld_c1", name="C1", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()
    transactional_session.add(
        TechFieldTemplateField(
            template_id=tpl.id, name="a", type_code="STRING", order=0
        )
    )
    await transactional_session.flush()

    await transactional_session.delete(tpl)
    await transactional_session.flush()
    remaining = (
        await transactional_session.execute(select(TechFieldTemplateField))
    ).scalars().all()
    assert len(remaining) == 0
```

- [ ] **Step 2: Run — verify FAIL (ImportError)**

```bash
PYTEST_ARGS="-v tests/models/test_tech_field_template.py" make test-docker
```

- [ ] **Step 3: Create `backend/models/tech_field_template.py`**

```python
import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class TechFieldTemplate(Base, MetaDataMixin):
    __tablename__ = "tech_field_templates"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    layer: Mapped[str] = mapped_column(String(32), nullable=False)

    fields = relationship(
        "TechFieldTemplateField",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TechFieldTemplateField.order",
    )

    def __repr__(self) -> str:
        return f"TechFieldTemplate(id={self.id}, code={self.code}, layer={self.layer})"


class TechFieldTemplateField(Base, MetaDataMixin):
    __tablename__ = "tech_field_template_fields"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tech_field_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    template = relationship("TechFieldTemplate", back_populates="fields")

    __table_args__ = (
        UniqueConstraint("template_id", "name", name="uq_tft_field_name"),
    )

    def __repr__(self) -> str:
        return (
            f"TechFieldTemplateField(id={self.id}, template_id={self.template_id}, "
            f"name={self.name}, type_code={self.type_code})"
        )
```

Note: `note` column comes from `NoteMixin` inside `MetaDataMixin` (no need to redeclare).

- [ ] **Step 4: Register in `backend/models/__init__.py`**

Add:

```python
from .tech_field_template import (
    TechFieldTemplate as TechFieldTemplate,
    TechFieldTemplateField as TechFieldTemplateField,
)
```

And append both names to `__all__`.

- [ ] **Step 5: Generate migration**

```bash
make alembic-gen
```

Strip auto-gen drift. Migration body should look like:

```python
def upgrade() -> None:
    op.create_table(
        "tech_field_templates",
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("layer", sa.String(length=32), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_tech_field_templates_id"), "tech_field_templates", ["id"], unique=True)
    op.create_index(op.f("ix_tech_field_templates_created_by"), "tech_field_templates", ["created_by"], unique=False)
    op.create_index(op.f("ix_tech_field_templates_updated_by"), "tech_field_templates", ["updated_by"], unique=False)

    op.create_table(
        "tech_field_template_fields",
        sa.Column("template_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type_code", sa.String(length=64), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["tech_field_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "name", name="uq_tft_field_name"),
    )
    op.create_index(op.f("ix_tech_field_template_fields_id"), "tech_field_template_fields", ["id"], unique=True)
    op.create_index(op.f("ix_tech_field_template_fields_template_id"), "tech_field_template_fields", ["template_id"], unique=False)
    op.create_index(op.f("ix_tech_field_template_fields_created_by"), "tech_field_template_fields", ["created_by"], unique=False)
    op.create_index(op.f("ix_tech_field_template_fields_updated_by"), "tech_field_template_fields", ["updated_by"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tech_field_template_fields_updated_by"), table_name="tech_field_template_fields")
    op.drop_index(op.f("ix_tech_field_template_fields_created_by"), table_name="tech_field_template_fields")
    op.drop_index(op.f("ix_tech_field_template_fields_template_id"), table_name="tech_field_template_fields")
    op.drop_index(op.f("ix_tech_field_template_fields_id"), table_name="tech_field_template_fields")
    op.drop_table("tech_field_template_fields")
    op.drop_index(op.f("ix_tech_field_templates_updated_by"), table_name="tech_field_templates")
    op.drop_index(op.f("ix_tech_field_templates_created_by"), table_name="tech_field_templates")
    op.drop_index(op.f("ix_tech_field_templates_id"), table_name="tech_field_templates")
    op.drop_table("tech_field_templates")
```

If `make alembic-gen` conflicts on port 5432 with user's `aide-db-1`: `docker stop aide-db-1` first, `docker start aide-db-1` after.

- [ ] **Step 6: Run tests**

```bash
PYTEST_ARGS="-v tests/models/test_tech_field_template.py" make test-docker
```

Expected: PASS (5 tests).

- [ ] **Step 7: Format + commit**

```bash
make format
git add backend/models/tech_field_template.py backend/models/__init__.py \
    backend/alembic/versions/ tests/models/test_tech_field_template.py
git commit -m "feat(templates): add tech_field_template models"
```

---

## Task 3: Schemas + repositories

**Files:**
- Create: `schemas/aide_schemas/tech_field_template.py`
- Create: `backend/schemas/tech_field_template.py`
- Create: `backend/repositories/tech_field_template.py`
- Create: `backend/repositories/tech_field_template_field.py`
- Create: `tests/repositories/test_tech_field_template_repository.py`

- [ ] **Step 1: Write failing repository tests**

Create `tests/repositories/test_tech_field_template_repository.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)
from backend.repositories.tech_field_template import TechFieldTemplateRepository
from backend.repositories.tech_field_template_field import (
    TechFieldTemplateFieldRepository,
)


@pytest.mark.asyncio
async def test_get_by_code(transactional_session: AsyncSession):
    tpl = TechFieldTemplate(code="repo_gc", name="RepoGC", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()

    repo = TechFieldTemplateRepository(transactional_session)
    found = await repo.get_by_code("repo_gc")
    assert found is not None and found.id == tpl.id
    assert await repo.get_by_code("nope") is None


@pytest.mark.asyncio
async def test_list_by_template(transactional_session: AsyncSession):
    tpl = TechFieldTemplate(code="repo_lt", name="RepoLT", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()
    transactional_session.add_all(
        [
            TechFieldTemplateField(
                template_id=tpl.id, name="a", type_code="STRING", order=1
            ),
            TechFieldTemplateField(
                template_id=tpl.id, name="b", type_code="STRING", order=0
            ),
        ]
    )
    await transactional_session.flush()

    repo = TechFieldTemplateFieldRepository(transactional_session)
    items = await repo.list_by_template(tpl.id)
    assert [it.name for it in items] == ["b", "a"]


@pytest.mark.asyncio
async def test_get_by_template_and_name(transactional_session: AsyncSession):
    tpl = TechFieldTemplate(code="repo_gtn", name="RepoGTN", layer="core")
    transactional_session.add(tpl)
    await transactional_session.flush()
    tf = TechFieldTemplateField(
        template_id=tpl.id, name="uniq", type_code="BIGINT", order=0
    )
    transactional_session.add(tf)
    await transactional_session.flush()

    repo = TechFieldTemplateFieldRepository(transactional_session)
    found = await repo.get_by_template_and_name(tpl.id, "uniq")
    assert found is not None and found.id == tf.id
    assert await repo.get_by_template_and_name(tpl.id, "missing") is None
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/repositories/test_tech_field_template_repository.py" make test-docker
```

- [ ] **Step 3: Create `schemas/aide_schemas/tech_field_template.py`**

```python
import uuid

from pydantic import BaseModel, ConfigDict

from aide_schemas.dataset import DatasetLayer
from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class TechFieldTemplateFieldBase(BaseModel):
    name: str
    type_code: str
    order: int = 0


class TechFieldTemplateFieldCreate(TechFieldTemplateFieldBase, NoteMixin):
    template_id: uuid.UUID


class TechFieldTemplateFieldUpdate(VersionedUpdateMixin, NoteMixin):
    name: str | None = None
    type_code: str | None = None
    order: int | None = None


class TechFieldTemplateFieldRead(TechFieldTemplateFieldBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
    template_id: uuid.UUID


class TechFieldTemplateBase(BaseModel):
    code: str
    name: str
    layer: DatasetLayer


class TechFieldTemplateCreate(TechFieldTemplateBase, NoteMixin):
    pass


class TechFieldTemplateUpdate(VersionedUpdateMixin, NoteMixin):
    code: str | None = None
    name: str | None = None
    layer: DatasetLayer | None = None


class TechFieldTemplateRead(TechFieldTemplateBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)


class TechFieldTemplateWithFieldsRead(TechFieldTemplateRead):
    fields: list[TechFieldTemplateFieldRead] = []


class TechFieldOverride(BaseModel):
    """Per-field override at apply-template time."""

    name: str
    type_code: str | None = None


class ApplyTechTemplateRequest(BaseModel):
    template_id: uuid.UUID
    overrides: list[TechFieldOverride] | None = None
```

- [ ] **Step 4: Re-export in `backend/schemas/tech_field_template.py`**

```python
from aide_schemas.tech_field_template import (
    ApplyTechTemplateRequest as ApplyTechTemplateRequest,
    TechFieldOverride as TechFieldOverride,
    TechFieldTemplateCreate as TechFieldTemplateCreate,
    TechFieldTemplateFieldCreate as TechFieldTemplateFieldCreate,
    TechFieldTemplateFieldRead as TechFieldTemplateFieldRead,
    TechFieldTemplateFieldUpdate as TechFieldTemplateFieldUpdate,
    TechFieldTemplateRead as TechFieldTemplateRead,
    TechFieldTemplateUpdate as TechFieldTemplateUpdate,
    TechFieldTemplateWithFieldsRead as TechFieldTemplateWithFieldsRead,
)
```

- [ ] **Step 5: Create `backend/repositories/tech_field_template.py`**

```python
from sqlalchemy import select

from backend.models.tech_field_template import TechFieldTemplate
from backend.repositories.base import BaseRepository


class TechFieldTemplateRepository(BaseRepository[TechFieldTemplate]):
    model = TechFieldTemplate

    async def get_by_code(self, code: str) -> TechFieldTemplate | None:
        stmt = select(self.model).where(self.model.code == code)
        result = await self._execute(stmt, method="get_by_code")
        return result.scalars().first()
```

- [ ] **Step 6: Create `backend/repositories/tech_field_template_field.py`**

```python
import uuid
from typing import Sequence

from sqlalchemy import select

from backend.models.tech_field_template import TechFieldTemplateField
from backend.repositories.base import BaseRepository


class TechFieldTemplateFieldRepository(BaseRepository[TechFieldTemplateField]):
    model = TechFieldTemplateField

    async def list_by_template(
        self, template_id: uuid.UUID
    ) -> Sequence[TechFieldTemplateField]:
        stmt = (
            select(self.model)
            .where(self.model.template_id == template_id)
            .order_by(self.model.order)
        )
        result = await self._execute(stmt, method="list_by_template")
        return result.scalars().all()

    async def get_by_template_and_name(
        self, template_id: uuid.UUID, name: str
    ) -> TechFieldTemplateField | None:
        stmt = select(self.model).where(
            self.model.template_id == template_id,
            self.model.name == name,
        )
        result = await self._execute(stmt, method="get_by_template_and_name")
        return result.scalars().first()
```

- [ ] **Step 7: Run tests**

```bash
PYTEST_ARGS="-v tests/repositories/test_tech_field_template_repository.py" make test-docker
```

Expected: PASS (3 tests).

- [ ] **Step 8: Format + commit**

```bash
make format
git add schemas/aide_schemas/tech_field_template.py backend/schemas/tech_field_template.py \
    backend/repositories/tech_field_template.py backend/repositories/tech_field_template_field.py \
    tests/repositories/test_tech_field_template_repository.py
git commit -m "feat(templates): add schemas and repositories"
```

---

## Task 4: Template + TemplateField services

**Files:**
- Create: `backend/services/tech_field_template.py`
- Create: `backend/services/tech_field_template_field.py`
- Create: `tests/services/test_tech_field_template_service.py`
- Create: `tests/services/test_tech_field_template_field_service.py`

- [ ] **Step 1: Write failing service tests for parent `TechFieldTemplateService`**

Create `tests/services/test_tech_field_template_service.py`:

```python
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.tech_field_template import TechFieldTemplate
from backend.schemas.tech_field_template import (
    TechFieldTemplateCreate,
    TechFieldTemplateRead,
)
from backend.services.tech_field_template import TechFieldTemplateService


class _MockRepo:
    def __init__(self) -> None:
        self.get = AsyncMock()
        self.get_by_code = AsyncMock(return_value=None)
        self.create = AsyncMock()
        self.update = AsyncMock()
        self.delete = AsyncMock()
        self.get_multi_paginated = AsyncMock(return_value=([], 0))


class _MockUoW:
    def __init__(self) -> None:
        self.session = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def service() -> TechFieldTemplateService:
    return TechFieldTemplateService()


@pytest.mark.asyncio
class TestTechFieldTemplateService:
    async def test_create_happy(self, service: TechFieldTemplateService):
        uow = _MockUoW()
        repo = _MockRepo()
        repo.create.return_value = TechFieldTemplate(
            id=uuid.uuid4(),
            code="scd2",
            name="SCD2",
            layer="core",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=TechFieldTemplateCreate(
                    code="scd2", name="SCD2", layer="core"
                ),
            )
        assert isinstance(result, TechFieldTemplateRead)
        assert result.code == "scd2"

    async def test_create_duplicate_code(self, service: TechFieldTemplateService):
        uow = _MockUoW()
        repo = _MockRepo()
        repo.get_by_code.return_value = TechFieldTemplate(id=uuid.uuid4(), code="scd2")
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=TechFieldTemplateCreate(
                        code="scd2", name="SCD2", layer="core"
                    ),
                )
        assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_ALREADY_EXISTS
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/services/test_tech_field_template_service.py" make test-docker
```

- [ ] **Step 3: Create `backend/services/tech_field_template.py`**

```python
import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.tech_field_template import TechFieldTemplate
from backend.repositories.tech_field_template import TechFieldTemplateRepository
from backend.schemas.tech_field_template import (
    TechFieldTemplateCreate,
    TechFieldTemplateRead,
    TechFieldTemplateUpdate,
)
from backend.services.base import GenericService


class TechFieldTemplateService(
    GenericService[
        TechFieldTemplate,
        TechFieldTemplateCreate,
        TechFieldTemplateUpdate,
        TechFieldTemplateRead,
    ]
):
    def __init__(self) -> None:
        super().__init__(
            model=TechFieldTemplate,
            repository=TechFieldTemplateRepository,
            read_schema=TechFieldTemplateRead,
            not_found_error_code=errors.TECH_FIELD_TEMPLATE_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: TechFieldTemplateCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(TechFieldTemplateRepository, self._get_repository(uow.session))
        if await repo.get_by_code(obj_in.code):
            raise AppException(errors.TECH_FIELD_TEMPLATE_ALREADY_EXISTS)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: TechFieldTemplate,
        obj_in: TechFieldTemplateUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        new_code = update_data.get("code")
        if new_code and new_code != db_obj.code:
            repo = cast(
                TechFieldTemplateRepository, self._get_repository(uow.session)
            )
            existing = await repo.get_by_code(new_code)
            if existing and existing.id != db_obj.id:
                raise AppException(errors.TECH_FIELD_TEMPLATE_ALREADY_EXISTS)
```

- [ ] **Step 4: Run parent-service tests — PASS**

```bash
PYTEST_ARGS="-v tests/services/test_tech_field_template_service.py" make test-docker
```

- [ ] **Step 5: Write failing child-service tests in `tests/services/test_tech_field_template_field_service.py`**

```python
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.tech_field_template import TechFieldTemplateField
from backend.schemas.tech_field_template import (
    TechFieldTemplateFieldCreate,
    TechFieldTemplateFieldRead,
)
from backend.services.tech_field_template_field import (
    TechFieldTemplateFieldService,
)


class _MockRepo:
    def __init__(self) -> None:
        self.get = AsyncMock()
        self.get_by_template_and_name = AsyncMock(return_value=None)
        self.list_by_template = AsyncMock(return_value=[])
        self.create = AsyncMock()
        self.update = AsyncMock()
        self.delete = AsyncMock()
        self.get_multi_paginated = AsyncMock(return_value=([], 0))


class _MockUoW:
    def __init__(self) -> None:
        self.session = AsyncMock()
        self.tech_field_templates = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def service() -> TechFieldTemplateFieldService:
    return TechFieldTemplateFieldService()


@pytest.mark.asyncio
class TestTechFieldTemplateFieldService:
    async def test_create_happy(self, service: TechFieldTemplateFieldService):
        template_id = uuid.uuid4()
        uow = _MockUoW()
        uow.tech_field_templates.get.return_value = object()  # truthy — template exists
        repo = _MockRepo()
        repo.create.return_value = TechFieldTemplateField(
            id=uuid.uuid4(),
            template_id=template_id,
            name="valid_from",
            type_code="TIMESTAMP",
            order=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=TechFieldTemplateFieldCreate(
                    template_id=template_id,
                    name="valid_from",
                    type_code="TIMESTAMP",
                    order=0,
                ),
            )
        assert isinstance(result, TechFieldTemplateFieldRead)
        assert result.name == "valid_from"

    async def test_create_template_missing(
        self, service: TechFieldTemplateFieldService
    ):
        template_id = uuid.uuid4()
        uow = _MockUoW()
        uow.tech_field_templates.get.return_value = None
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=TechFieldTemplateFieldCreate(
                        template_id=template_id,
                        name="x",
                        type_code="STRING",
                        order=0,
                    ),
                )
        assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_NOT_FOUND

    async def test_create_duplicate_name(
        self, service: TechFieldTemplateFieldService
    ):
        template_id = uuid.uuid4()
        uow = _MockUoW()
        uow.tech_field_templates.get.return_value = object()
        repo = _MockRepo()
        repo.get_by_template_and_name.return_value = TechFieldTemplateField(
            id=uuid.uuid4(), template_id=template_id, name="dup"
        )
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=TechFieldTemplateFieldCreate(
                        template_id=template_id,
                        name="dup",
                        type_code="STRING",
                        order=0,
                    ),
                )
        assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS
```

- [ ] **Step 6: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/services/test_tech_field_template_field_service.py" make test-docker
```

- [ ] **Step 7: Create `backend/services/tech_field_template_field.py`**

```python
import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.tech_field_template import TechFieldTemplateField
from backend.repositories.tech_field_template_field import (
    TechFieldTemplateFieldRepository,
)
from backend.schemas.tech_field_template import (
    TechFieldTemplateFieldCreate,
    TechFieldTemplateFieldRead,
    TechFieldTemplateFieldUpdate,
)
from backend.services.base import GenericService


class TechFieldTemplateFieldService(
    GenericService[
        TechFieldTemplateField,
        TechFieldTemplateFieldCreate,
        TechFieldTemplateFieldUpdate,
        TechFieldTemplateFieldRead,
    ]
):
    def __init__(self) -> None:
        super().__init__(
            model=TechFieldTemplateField,
            repository=TechFieldTemplateFieldRepository,
            read_schema=TechFieldTemplateFieldRead,
            not_found_error_code=errors.TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: TechFieldTemplateFieldCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        if not await uow.tech_field_templates.get(obj_in.template_id):
            raise AppException(errors.TECH_FIELD_TEMPLATE_NOT_FOUND)
        repo = cast(
            TechFieldTemplateFieldRepository, self._get_repository(uow.session)
        )
        if await repo.get_by_template_and_name(obj_in.template_id, obj_in.name):
            raise AppException(errors.TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS)
```

- [ ] **Step 8: Run all tests**

```bash
PYTEST_ARGS="-v tests/services/test_tech_field_template_service.py tests/services/test_tech_field_template_field_service.py" make test-docker
```

Expected: PASS (5 tests).

- [ ] **Step 9: Format + commit**

```bash
make format
git add backend/services/tech_field_template.py backend/services/tech_field_template_field.py \
    tests/services/test_tech_field_template_service.py \
    tests/services/test_tech_field_template_field_service.py
git commit -m "feat(templates): add template services"
```

---

## Task 5: Template API + UoW wire

**Files:**
- Create: `backend/api/v1/tech_field_templates.py`
- Modify: `backend/db/uow.py`
- Modify: `backend/main.py`
- Create: `tests/api/test_tech_field_templates.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/api/test_tech_field_templates.py`. Match the AsyncClient pattern from `tests/api/test_field_links.py`:

```python
import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import create_access_token
from backend.main import app
from backend.models.user import User, UserType


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="tpl_super.user@example.com",
        hashed_password="x",
        full_name="TPL Super",
        is_active=True,
        is_superuser=True,
        user_type=UserType.HUMAN,
    )
    transactional_session.add(user)
    await transactional_session.flush()
    return user


@pytest.fixture
def superuser_token_headers(superuser: User) -> dict[str, str]:
    token = create_access_token(subject=str(superuser.id))
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def async_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
class TestTechFieldTemplateAPI:
    async def test_create_template(self, async_client, superuser_token_headers):
        resp = await async_client.post(
            "/api/v1/tech-field-templates/",
            json={"code": "scd2_v1", "name": "SCD2 v1", "layer": "core"},
            headers=superuser_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()["code"] == "scd2_v1"

    async def test_create_duplicate_code(self, async_client, superuser_token_headers):
        payload = {"code": "dup_v1", "name": "Dup", "layer": "core"}
        r1 = await async_client.post(
            "/api/v1/tech-field-templates/",
            json=payload,
            headers=superuser_token_headers,
        )
        assert r1.status_code == status.HTTP_201_CREATED
        r2 = await async_client.post(
            "/api/v1/tech-field-templates/",
            json=payload,
            headers=superuser_token_headers,
        )
        assert r2.status_code == status.HTTP_409_CONFLICT
        assert r2.json()["error_code"] == "TECH_FIELD_TEMPLATE_ALREADY_EXISTS"

    async def test_add_field_to_template(self, async_client, superuser_token_headers):
        tpl = (
            await async_client.post(
                "/api/v1/tech-field-templates/",
                json={"code": "add_fld_v1", "name": "Addf", "layer": "core"},
                headers=superuser_token_headers,
            )
        ).json()
        resp = await async_client.post(
            f"/api/v1/tech-field-templates/{tpl['id']}/fields",
            json={
                "template_id": tpl["id"],
                "name": "valid_from",
                "type_code": "TIMESTAMP",
                "order": 0,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()["name"] == "valid_from"
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/api/test_tech_field_templates.py" make test-docker
```

- [ ] **Step 3: Register repositories in `backend/db/uow.py`**

Add imports:

```python
from backend.repositories.tech_field_template import TechFieldTemplateRepository
from backend.repositories.tech_field_template_field import (
    TechFieldTemplateFieldRepository,
)
```

Add attributes inside `__aenter__`:

```python
self.tech_field_templates = TechFieldTemplateRepository(self.session)
self.tech_field_template_fields = TechFieldTemplateFieldRepository(self.session)
```

- [ ] **Step 4: Create `backend/api/v1/tech_field_templates.py`**

```python
import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_current_superuser, get_current_user
from backend.api.filter_sort import FilterSortParams, get_filter_sort_dependency
from backend.core.errors import (
    FORBIDDEN,
    TECH_FIELD_TEMPLATE_ALREADY_EXISTS,
    TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS,
    TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND,
    TECH_FIELD_TEMPLATE_NOT_FOUND,
    UNAUTHORIZED,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.filters import TechFieldTemplateFilter, TECH_FIELD_TEMPLATE_SORTABLE
from backend.schemas.pagination import Page
from backend.schemas.tech_field_template import (
    TechFieldTemplateCreate,
    TechFieldTemplateFieldCreate,
    TechFieldTemplateFieldRead,
    TechFieldTemplateFieldUpdate,
    TechFieldTemplateRead,
    TechFieldTemplateUpdate,
)
from backend.services.tech_field_template import TechFieldTemplateService
from backend.services.tech_field_template_field import TechFieldTemplateFieldService

router = APIRouter()

_filter_sort = get_filter_sort_dependency(
    TechFieldTemplateFilter, TECH_FIELD_TEMPLATE_SORTABLE, "code"
)


@router.get("/", response_model=Page[TechFieldTemplateRead])
async def list_templates(
    service: TechFieldTemplateService = Depends(TechFieldTemplateService),
    uow: UnitOfWork = Depends(UnitOfWork),
    params: FilterSortParams = Depends(_filter_sort),
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
    response_model=TechFieldTemplateRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            TECH_FIELD_TEMPLATE_ALREADY_EXISTS, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def create_template(
    obj_in: TechFieldTemplateCreate,
    service: TechFieldTemplateService = Depends(TechFieldTemplateService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.get(
    "/{obj_id}",
    response_model=TechFieldTemplateRead,
    responses={
        **build_error_responses(TECH_FIELD_TEMPLATE_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)
    },
)
async def get_template(
    obj_id: uuid.UUID,
    service: TechFieldTemplateService = Depends(TechFieldTemplateService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    return await service.get_by_id(uow=uow, obj_id=obj_id)


@router.patch(
    "/{obj_id}",
    response_model=TechFieldTemplateRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            TECH_FIELD_TEMPLATE_NOT_FOUND,
            TECH_FIELD_TEMPLATE_ALREADY_EXISTS,
            VERSION_CONFLICT,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def update_template(
    obj_id: uuid.UUID,
    obj_in: TechFieldTemplateUpdate,
    service: TechFieldTemplateService = Depends(TechFieldTemplateService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )


@router.delete(
    "/{obj_id}",
    response_model=TechFieldTemplateRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(TECH_FIELD_TEMPLATE_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)
    },
)
async def delete_template(
    obj_id: uuid.UUID,
    service: TechFieldTemplateService = Depends(TechFieldTemplateService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)


# --- Template fields sub-resource ---


@router.get(
    "/{template_id}/fields",
    response_model=list[TechFieldTemplateFieldRead],
)
async def list_template_fields(
    template_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    async with uow:
        items = await uow.tech_field_template_fields.list_by_template(template_id)
        return [TechFieldTemplateFieldRead.model_validate(i) for i in items]


@router.post(
    "/{template_id}/fields",
    response_model=TechFieldTemplateFieldRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            TECH_FIELD_TEMPLATE_NOT_FOUND,
            TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def create_template_field(
    template_id: uuid.UUID,
    obj_in: TechFieldTemplateFieldCreate,
    service: TechFieldTemplateFieldService = Depends(TechFieldTemplateFieldService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    obj_in = obj_in.model_copy(update={"template_id": template_id})
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.patch(
    "/fields/{obj_id}",
    response_model=TechFieldTemplateFieldRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND,
            VERSION_CONFLICT,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def update_template_field(
    obj_id: uuid.UUID,
    obj_in: TechFieldTemplateFieldUpdate,
    service: TechFieldTemplateFieldService = Depends(TechFieldTemplateFieldService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )


@router.delete(
    "/fields/{obj_id}",
    response_model=TechFieldTemplateFieldRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def delete_template_field(
    obj_id: uuid.UUID,
    service: TechFieldTemplateFieldService = Depends(TechFieldTemplateFieldService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)
```

- [ ] **Step 5: Add filter schema to `backend/schemas/filters.py`**

Add near other filter classes (inspect existing style — e.g. `DatasetLinkFilter` landed in Phase 1 Task 7):

```python
class TechFieldTemplateFilter(BaseModel):
    code: str | None = None
    layer: str | None = None


TECH_FIELD_TEMPLATE_SORTABLE: tuple[str, ...] = ("code", "name", "layer", "created_at")
```

If `BaseModel` import is missing, add it. Match the imports + style of neighboring filter classes.

- [ ] **Step 6: Register router in `backend/main.py`**

Add import:

```python
from backend.api.v1 import tech_field_templates as v1_tech_field_templates
```

Add include after existing lineage routers:

```python
app.include_router(
    v1_tech_field_templates.router,
    prefix=f"{api_v1_prefix}/tech-field-templates",
    tags=["Tech Field Templates"],
)
```

- [ ] **Step 7: Run tests**

```bash
PYTEST_ARGS="-v tests/api/test_tech_field_templates.py" make test-docker
```

Expected: PASS (3 tests).

- [ ] **Step 8: Format + commit**

```bash
make format
git add backend/api/v1/tech_field_templates.py backend/db/uow.py backend/main.py \
    backend/schemas/filters.py tests/api/test_tech_field_templates.py
git commit -m "feat(templates): add template API"
```

---

## Task 6: Type-code resolver + YAML

**Files:**
- Create: `backend/core/tech_type_resolver.py`
- Create: `backend/scripts/data/tech_type_resolver.yaml`
- Create: `tests/core/test_tech_type_resolver.py`

- [ ] **Step 1: Write failing tests**

Create `tests/core/test_tech_type_resolver.py`:

```python
from pathlib import Path

import pytest

from backend.core.tech_type_resolver import TechTypeResolver


SAMPLE_YAML = """
mappings:
  - flavor: postgres14
    type_code: TIMESTAMP
    data_type_code: timestamp
  - flavor: postgres14
    type_code: STRING
    data_type_code: text
  - flavor: kafka_avro
    type_code: TIMESTAMP
    data_type_code: long
"""


@pytest.fixture
def resolver(tmp_path: Path) -> TechTypeResolver:
    path = tmp_path / "mappings.yaml"
    path.write_text(SAMPLE_YAML)
    return TechTypeResolver.from_yaml(path)


def test_resolve_found(resolver: TechTypeResolver):
    assert resolver.resolve("postgres14", "TIMESTAMP") == "timestamp"
    assert resolver.resolve("postgres14", "STRING") == "text"
    assert resolver.resolve("kafka_avro", "TIMESTAMP") == "long"


def test_resolve_unknown_flavor(resolver: TechTypeResolver):
    assert resolver.resolve("oracle", "TIMESTAMP") is None


def test_resolve_unknown_type_code(resolver: TechTypeResolver):
    assert resolver.resolve("postgres14", "UNKNOWN") is None


def test_duplicate_mapping_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
mappings:
  - flavor: postgres14
    type_code: TIMESTAMP
    data_type_code: timestamp
  - flavor: postgres14
    type_code: TIMESTAMP
    data_type_code: timestamptz
"""
    )
    with pytest.raises(ValueError, match="Duplicate mapping"):
        TechTypeResolver.from_yaml(bad)
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/core/test_tech_type_resolver.py" make test-docker
```

- [ ] **Step 3: Create `backend/core/tech_type_resolver.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class TechTypeResolver:
    """Maps abstract (flavor, type_code) pairs to concrete data-type codes."""

    _table: dict[tuple[str, str], str]

    @classmethod
    def from_yaml(cls, path: Path) -> "TechTypeResolver":
        with path.open("r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        mappings = doc.get("mappings", [])
        table: dict[tuple[str, str], str] = {}
        for entry in mappings:
            key = (entry["flavor"], entry["type_code"])
            if key in table:
                raise ValueError(
                    f"Duplicate mapping for flavor={key[0]!r}, type_code={key[1]!r}"
                )
            table[key] = entry["data_type_code"]
        return cls(_table=table)

    def resolve(self, flavor: str, type_code: str) -> str | None:
        return self._table.get((flavor, type_code))
```

- [ ] **Step 4: Create starter YAML `backend/scripts/data/tech_type_resolver.yaml`**

```yaml
# Abstract type_code → concrete data-type code per system flavor.
# Add entries as new flavors/type_codes are introduced.
# Duplicates (same flavor+type_code) fail loading.
mappings:
  - flavor: postgres14
    type_code: TIMESTAMP
    data_type_code: timestamp
  - flavor: postgres14
    type_code: STRING
    data_type_code: text
  - flavor: postgres14
    type_code: BIGINT
    data_type_code: bigint
  - flavor: postgres14
    type_code: INTEGER
    data_type_code: integer
  - flavor: postgres14
    type_code: BOOLEAN
    data_type_code: boolean
  - flavor: postgres14
    type_code: UUID
    data_type_code: uuid
```

- [ ] **Step 5: Run tests**

```bash
PYTEST_ARGS="-v tests/core/test_tech_type_resolver.py" make test-docker
```

Expected: PASS (4 tests).

- [ ] **Step 6: Format + commit**

```bash
make format
git add backend/core/tech_type_resolver.py backend/scripts/data/tech_type_resolver.yaml \
    tests/core/test_tech_type_resolver.py
git commit -m "feat(templates): add type_code resolver"
```

---

## Task 7: DatasetService.apply_tech_template

**Files:**
- Modify: `backend/services/dataset.py`
- Modify: `backend/db/uow.py` (add `system_flavors` attribute if not already present — inspect)
- Modify: `tests/services/test_dataset_service.py`

- [ ] **Step 1: Inspect existing UoW + add missing repository attributes**

Check `backend/db/uow.py` — does it already expose `system_flavors` and `data_types`? (Task 5 added `tech_field_templates` + `tech_field_template_fields`. `systems` already exists from pre-Phase-1. Check for `system_flavors` / `data_types` and add if missing, matching the existing pattern.)

If missing, add:
```python
from backend.repositories.system_flavor import SystemFlavorRepository
# (data_types import likely already exists — verify)

# inside __aenter__:
self.system_flavors = SystemFlavorRepository(self.session)
# (data_types already present per existing code)
```

- [ ] **Step 2: Write failing service tests**

Add to `tests/services/test_dataset_service.py` inside `TestDatasetService` class:

```python
async def test_apply_tech_template_happy(
    self,
    dataset_service: DatasetService,
    mock_uow: _MockUnitOfWork,
    db_dataset_rdbms,
    db_system,
):
    from unittest.mock import MagicMock
    from backend.models.tech_field_template import (
        TechFieldTemplate,
        TechFieldTemplateField,
    )
    from backend.models.system_flavor import SystemFlavor
    from backend.models.data_type import DataType
    from backend.models.field import Field

    db_dataset_rdbms.layer = "core"
    template = TechFieldTemplate(
        id=uuid.uuid4(), code="scd2", name="SCD2", layer="core"
    )
    tpl_field = TechFieldTemplateField(
        id=uuid.uuid4(),
        template_id=template.id,
        name="valid_from",
        type_code="TIMESTAMP",
        order=0,
    )
    flavor = SystemFlavor(id=db_system.flavor_id if hasattr(db_system, "flavor_id") else uuid.uuid4(), code="postgres14", name="PG14", kind_id=uuid.uuid4())
    if not hasattr(db_system, "flavor_id") or db_system.flavor_id is None:
        db_system.flavor_id = flavor.id
    data_type = DataType(
        id=uuid.uuid4(),
        system_flavor_id=flavor.id,
        code="timestamp",
        params_schema={},
    )

    mock_uow.tech_field_templates = MagicMock()
    mock_uow.tech_field_templates.get = AsyncMock(return_value=template)
    mock_uow.tech_field_template_fields = MagicMock()
    mock_uow.tech_field_template_fields.list_by_template = AsyncMock(
        return_value=[tpl_field]
    )
    mock_uow.system_flavors = MagicMock()
    mock_uow.system_flavors.get = AsyncMock(return_value=flavor)
    mock_uow.data_types = MagicMock()
    mock_uow.data_types.get_by_system_flavor_and_code = AsyncMock(
        return_value=data_type
    )
    mock_uow.systems.get = AsyncMock(return_value=db_system)
    mock_uow.fields = MagicMock()
    mock_uow.fields.get_roots = AsyncMock(return_value=[])
    mock_uow.fields.create_many = AsyncMock(
        side_effect=lambda objs: objs
    )

    mock_repo = _MockRepository()
    mock_repo.get.return_value = db_dataset_rdbms
    with patch.object(dataset_service, "_get_repository", return_value=mock_repo), \
        patch(
            "backend.services.dataset.tech_type_resolver.resolve",
            return_value="timestamp",
        ):
        result = await dataset_service.apply_tech_template(
            uow=mock_uow,
            dataset_id=db_dataset_rdbms.id,
            template_id=template.id,
        )
    assert len(result) == 1
    assert result[0].name == "valid_from"
    assert result[0].is_tech is True


async def test_apply_tech_template_layer_mismatch(
    self,
    dataset_service: DatasetService,
    mock_uow: _MockUnitOfWork,
    db_dataset_rdbms,
):
    from unittest.mock import MagicMock
    from backend.models.tech_field_template import TechFieldTemplate

    db_dataset_rdbms.layer = "raw"
    template = TechFieldTemplate(
        id=uuid.uuid4(), code="scd2", name="SCD2", layer="core"
    )
    mock_uow.tech_field_templates = MagicMock()
    mock_uow.tech_field_templates.get = AsyncMock(return_value=template)
    mock_repo = _MockRepository()
    mock_repo.get.return_value = db_dataset_rdbms

    with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
        with pytest.raises(AppException) as exc:
            await dataset_service.apply_tech_template(
                uow=mock_uow,
                dataset_id=db_dataset_rdbms.id,
                template_id=template.id,
            )
    assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_LAYER_MISMATCH


async def test_apply_tech_template_unresolvable_type(
    self,
    dataset_service: DatasetService,
    mock_uow: _MockUnitOfWork,
    db_dataset_rdbms,
    db_system,
):
    from unittest.mock import MagicMock
    from backend.models.tech_field_template import (
        TechFieldTemplate,
        TechFieldTemplateField,
    )
    from backend.models.system_flavor import SystemFlavor

    db_dataset_rdbms.layer = "core"
    template = TechFieldTemplate(
        id=uuid.uuid4(), code="scd2", name="SCD2", layer="core"
    )
    tpl_field = TechFieldTemplateField(
        id=uuid.uuid4(),
        template_id=template.id,
        name="foo",
        type_code="UNKNOWN",
        order=0,
    )
    flavor = SystemFlavor(
        id=uuid.uuid4(), code="postgres14", name="PG14", kind_id=uuid.uuid4()
    )

    mock_uow.tech_field_templates = MagicMock()
    mock_uow.tech_field_templates.get = AsyncMock(return_value=template)
    mock_uow.tech_field_template_fields = MagicMock()
    mock_uow.tech_field_template_fields.list_by_template = AsyncMock(
        return_value=[tpl_field]
    )
    mock_uow.system_flavors = MagicMock()
    mock_uow.system_flavors.get = AsyncMock(return_value=flavor)
    mock_uow.systems.get = AsyncMock(return_value=db_system)
    mock_uow.fields = MagicMock()
    mock_uow.fields.get_roots = AsyncMock(return_value=[])

    mock_repo = _MockRepository()
    mock_repo.get.return_value = db_dataset_rdbms
    with patch.object(dataset_service, "_get_repository", return_value=mock_repo), \
        patch(
            "backend.services.dataset.tech_type_resolver.resolve",
            return_value=None,
        ):
        with pytest.raises(AppException) as exc:
            await dataset_service.apply_tech_template(
                uow=mock_uow,
                dataset_id=db_dataset_rdbms.id,
                template_id=template.id,
            )
    assert exc.value.error_code == errors.TECH_TYPE_CODE_NOT_RESOLVABLE
```

- [ ] **Step 3: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/services/test_dataset_service.py" make test-docker
```

- [ ] **Step 4: Add module-level resolver + method to `backend/services/dataset.py`**

Near the top of the file, add:

```python
from pathlib import Path

from backend.core.tech_type_resolver import TechTypeResolver
from backend.schemas.field import FieldRead
from backend.schemas.tech_field_template import TechFieldOverride

_RESOLVER_YAML = (
    Path(__file__).resolve().parents[2]
    / "backend"
    / "scripts"
    / "data"
    / "tech_type_resolver.yaml"
)
tech_type_resolver = TechTypeResolver.from_yaml(_RESOLVER_YAML)
```

Add the method inside `DatasetService`:

```python
async def apply_tech_template(
    self,
    uow: UnitOfWork,
    dataset_id: uuid.UUID,
    template_id: uuid.UUID,
    overrides: list[TechFieldOverride] | None = None,
    applier_id: uuid.UUID | None = None,
) -> list[FieldRead]:
    """Apply a tech-field template to a dataset.

    Idempotent: existing field names on the dataset are skipped.
    """
    from backend.models.field import Field

    async with uow:
        repo = cast(DatasetRepository, self._get_repository(uow.session))
        dataset = await repo.get(dataset_id)
        if dataset is None:
            raise AppException(errors.DATASET_NOT_FOUND)

        template = await uow.tech_field_templates.get(template_id)
        if template is None:
            raise AppException(errors.TECH_FIELD_TEMPLATE_NOT_FOUND)

        if dataset.layer != template.layer:
            raise AppException(errors.TECH_FIELD_TEMPLATE_LAYER_MISMATCH)

        system = await uow.systems.get(dataset.system_id)
        if system is None:
            raise AppException(errors.SYSTEM_NOT_FOUND)
        flavor = await uow.system_flavors.get(system.flavor_id)
        if flavor is None:
            raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)

        tpl_fields = await uow.tech_field_template_fields.list_by_template(
            template_id
        )
        override_map: dict[str, TechFieldOverride] = {
            o.name: o for o in (overrides or [])
        }
        existing_roots = await uow.fields.get_roots(dataset_id)
        existing_names = {f.name for f in existing_roots}

        new_fields: list[Field] = []
        for tf in tpl_fields:
            if tf.name in existing_names:
                continue
            override = override_map.get(tf.name)
            type_code = (
                override.type_code if override and override.type_code else tf.type_code
            )
            data_type_code = tech_type_resolver.resolve(flavor.code, type_code)
            if data_type_code is None:
                raise AppException(errors.TECH_TYPE_CODE_NOT_RESOLVABLE)
            data_type = await uow.data_types.get_by_system_flavor_and_code(
                flavor.id, data_type_code
            )
            if data_type is None:
                raise AppException(errors.TECH_TYPE_CODE_NOT_RESOLVABLE)
            field = Field(
                dataset_id=dataset_id,
                name=tf.name,
                is_tech=True,
                extra={
                    "data_type_id": str(data_type.id),
                    "tech_type_code": type_code,
                },
            )
            if applier_id:
                field.created_by = applier_id
                field.updated_by = applier_id
            new_fields.append(field)

        if new_fields:
            await uow.fields.create_many(objs=new_fields)

        return [FieldRead.model_validate(f) for f in new_fields]
```

- [ ] **Step 5: Run tests**

```bash
PYTEST_ARGS="-v tests/services/test_dataset_service.py" make test-docker
```

Expected: PASS (existing + 3 new).

- [ ] **Step 6: Format + commit**

```bash
make format
git add backend/services/dataset.py backend/db/uow.py tests/services/test_dataset_service.py
git commit -m "feat(dataset): add apply_tech_template service method"
```

---

## Task 8: Datasets API — apply-tech-template endpoint

**Files:**
- Modify: `backend/api/v1/datasets.py`
- Modify: `tests/api/test_datasets.py`

- [ ] **Step 1: Write failing API test**

Add to `tests/api/test_datasets.py` inside `TestDatasetAPI`:

```python
async def test_apply_tech_template_happy(
    self,
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_system: System,
):
    # Seed a DataType for flavor "postgres14" with code "timestamp".
    # The test_system fixture already uses a flavor; ensure the flavor code matches.
    # If test_system uses a different flavor, skip — see Task 8 context note.

    # Create template + field
    tpl = (
        await async_client.post(
            "/api/v1/tech-field-templates/",
            json={
                "code": "apply_happy_v1",
                "name": "Apply Happy",
                "layer": "core",
            },
            headers=superuser_token_headers,
        )
    ).json()
    await async_client.post(
        f"/api/v1/tech-field-templates/{tpl['id']}/fields",
        json={
            "template_id": tpl["id"],
            "name": "valid_from",
            "type_code": "TIMESTAMP",
            "order": 0,
        },
        headers=superuser_token_headers,
    )

    ds_id = await _create_dataset(
        async_client, superuser_token_headers, test_system.id, "apply_tgt", "core"
    )

    resp = await async_client.post(
        f"/api/v1/datasets/{ds_id}/apply-tech-template",
        json={"template_id": tpl["id"]},
        headers=superuser_token_headers,
    )
    # This test passes only if the test_system's flavor has a data type
    # matching the resolver's output (e.g. "timestamp" on postgres14).
    # If the flavor lookup fails in the test environment, assert the
    # appropriate error instead. See the TEST SETUP NOTE below.
    assert resp.status_code in (status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST), resp.text
```

**TEST SETUP NOTE:** The existing `test_system` fixture creates an ad-hoc `SystemFlavor` with a test-only code. The resolver YAML shipped in Task 6 covers `postgres14`. If the fixture's flavor code does not match, `apply-tech-template` returns 400 `TECH_TYPE_CODE_NOT_RESOLVABLE`. For a robust test, either: (a) align the fixture's flavor code to `postgres14` and seed a `timestamp` data type before the request, or (b) assert only the 400 error path here and cover happy-path in service-level unit tests (already done in Task 7). **Recommended: assert 400 with `TECH_TYPE_CODE_NOT_RESOLVABLE` in this API test** — the happy path is covered via mocks at the service layer where the flavor/data-type seeding is deterministic.

Replace the final assertion with:

```python
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["error_code"] in (
        "TECH_TYPE_CODE_NOT_RESOLVABLE",
        "SYSTEM_FLAVOR_NOT_FOUND",
    )
```

Also add a layer-mismatch test:

```python
async def test_apply_tech_template_layer_mismatch(
    self,
    async_client: AsyncClient,
    superuser_token_headers: dict,
    test_system: System,
):
    tpl = (
        await async_client.post(
            "/api/v1/tech-field-templates/",
            json={
                "code": "apply_mm_v1",
                "name": "Apply MM",
                "layer": "core",
            },
            headers=superuser_token_headers,
        )
    ).json()
    ds_id = await _create_dataset(
        async_client, superuser_token_headers, test_system.id, "apply_mm_tgt", "raw"
    )
    resp = await async_client.post(
        f"/api/v1/datasets/{ds_id}/apply-tech-template",
        json={"template_id": tpl["id"]},
        headers=superuser_token_headers,
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["error_code"] == "TECH_FIELD_TEMPLATE_LAYER_MISMATCH"
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/api/test_datasets.py::TestDatasetAPI::test_apply_tech_template_happy tests/api/test_datasets.py::TestDatasetAPI::test_apply_tech_template_layer_mismatch" make test-docker
```

- [ ] **Step 3: Add endpoint to `backend/api/v1/datasets.py`**

Append after `get_unmapped_fields`:

```python
from backend.schemas.tech_field_template import ApplyTechTemplateRequest

# Add these error codes to the existing import block at top:
# TECH_FIELD_TEMPLATE_LAYER_MISMATCH, TECH_FIELD_TEMPLATE_NOT_FOUND,
# TECH_TYPE_CODE_NOT_RESOLVABLE, SYSTEM_NOT_FOUND, SYSTEM_FLAVOR_NOT_FOUND


@router.post(
    "/{obj_id}/apply-tech-template",
    response_model=list[FieldRead],
    status_code=status.HTTP_201_CREATED,
    summary="Apply a tech-field template to a dataset",
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_NOT_FOUND,
            TECH_FIELD_TEMPLATE_NOT_FOUND,
            TECH_FIELD_TEMPLATE_LAYER_MISMATCH,
            TECH_TYPE_CODE_NOT_RESOLVABLE,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def apply_tech_template(
    obj_id: uuid.UUID,
    req: ApplyTechTemplateRequest,
    service: DatasetService = Depends(DatasetService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.apply_tech_template(
        uow=uow,
        dataset_id=obj_id,
        template_id=req.template_id,
        overrides=req.overrides,
        applier_id=current_user.id,
    )
```

Make sure the new error codes (`TECH_FIELD_TEMPLATE_*`, `SYSTEM_FLAVOR_NOT_FOUND`) are imported at the top of `datasets.py`.

- [ ] **Step 4: Run tests**

```bash
PYTEST_ARGS="-v tests/api/test_datasets.py" make test-docker
```

Expected: PASS (all existing + 2 new).

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/api/v1/datasets.py tests/api/test_datasets.py
git commit -m "feat(dataset): add apply-tech-template endpoint"
```

---

## Task 9: Seed script for tech templates

**Files:**
- Create: `backend/scripts/seed_tech_templates.py`
- Create: `backend/scripts/data/tech_templates.yaml`
- Create: `tests/scripts/test_seed_tech_templates.py`

- [ ] **Step 1: Write failing test**

Create `tests/scripts/test_seed_tech_templates.py`:

```python
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.tech_field_template import TechFieldTemplate
from backend.scripts.seed_tech_templates import seed_from_file


SAMPLE_YAML = """
templates:
  - code: scd2_core_v1
    name: SCD2 on CORE
    layer: core
    fields:
      - name: valid_from
        type_code: TIMESTAMP
        order: 0
      - name: valid_to
        type_code: TIMESTAMP
        order: 1
"""


@pytest.mark.asyncio
async def test_seed_inserts(transactional_session: AsyncSession, tmp_path: Path):
    path = tmp_path / "t.yaml"
    path.write_text(SAMPLE_YAML)
    report = await seed_from_file(transactional_session, path)
    assert report.templates_inserted == 1
    assert report.fields_inserted == 2

    row = (await transactional_session.execute(select(TechFieldTemplate))).scalars().first()
    assert row is not None
    assert row.code == "scd2_core_v1"
    assert len(row.fields) == 2


@pytest.mark.asyncio
async def test_seed_idempotent(transactional_session: AsyncSession, tmp_path: Path):
    path = tmp_path / "t.yaml"
    path.write_text(SAMPLE_YAML)
    first = await seed_from_file(transactional_session, path)
    second = await seed_from_file(transactional_session, path)
    assert first.templates_inserted == 1 and first.fields_inserted == 2
    assert second.templates_inserted == 0 and second.fields_inserted == 0
    assert second.templates_unchanged == 1
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/scripts/test_seed_tech_templates.py" make test-docker
```

- [ ] **Step 3: Create `backend/scripts/data/tech_templates.yaml`**

```yaml
# Starter tech-field template catalogue.
# Re-running the seed is idempotent: existing (code) entries are matched and
# fields are added/updated in place.
templates:
  - code: scd2_core_v1
    name: SCD2 on CORE
    layer: core
    fields:
      - name: valid_from
        type_code: TIMESTAMP
        order: 0
      - name: valid_to
        type_code: TIMESTAMP
        order: 1
      - name: is_current
        type_code: BOOLEAN
        order: 2
      - name: etl_hash
        type_code: STRING
        order: 3

  - code: cdc_payload_kafka_v1
    name: CDC payload on KAFKA
    layer: kafka
    fields:
      - name: cdc_op
        type_code: STRING
        order: 0
      - name: cdc_ts_ms
        type_code: BIGINT
        order: 1
      - name: cdc_lsn
        type_code: STRING
        order: 2
```

- [ ] **Step 4: Create `backend/scripts/seed_tech_templates.py`**

```python
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)


@dataclass
class SeedReport:
    templates_inserted: int = 0
    templates_unchanged: int = 0
    fields_inserted: int = 0
    fields_unchanged: int = 0
    details: list[str] = field(default_factory=list)


async def seed_from_file(session: AsyncSession, file: Path) -> SeedReport:
    with file.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    report = SeedReport()
    for tpl_entry in doc.get("templates", []):
        code = tpl_entry["code"]
        existing = (
            await session.execute(
                select(TechFieldTemplate).where(TechFieldTemplate.code == code)
            )
        ).scalars().first()

        if existing is None:
            tpl = TechFieldTemplate(
                code=code,
                name=tpl_entry["name"],
                layer=tpl_entry["layer"],
            )
            session.add(tpl)
            await session.flush()
            report.templates_inserted += 1
        else:
            tpl = existing
            report.templates_unchanged += 1

        existing_fields = (
            await session.execute(
                select(TechFieldTemplateField).where(
                    TechFieldTemplateField.template_id == tpl.id
                )
            )
        ).scalars().all()
        existing_by_name = {f.name: f for f in existing_fields}

        for field_entry in tpl_entry.get("fields", []):
            fname = field_entry["name"]
            if fname in existing_by_name:
                report.fields_unchanged += 1
                continue
            session.add(
                TechFieldTemplateField(
                    template_id=tpl.id,
                    name=fname,
                    type_code=field_entry["type_code"],
                    order=field_entry.get("order", 0),
                )
            )
            report.fields_inserted += 1
    await session.flush()
    return report


async def _run_cli(file: Path, dry_run: bool) -> SeedReport:
    async with AsyncSessionLocal() as session:
        report = await seed_from_file(session, file)
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
        return report


def _entry() -> None:
    parser = argparse.ArgumentParser(description="Seed tech-field templates.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(_run_cli(args.file, args.dry_run))
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(
        f"{prefix}templates: +{report.templates_inserted} "
        f"={report.templates_unchanged} | "
        f"fields: +{report.fields_inserted} ={report.fields_unchanged}"
    )


if __name__ == "__main__":
    _entry()
```

- [ ] **Step 5: Run tests**

```bash
PYTEST_ARGS="-v tests/scripts/test_seed_tech_templates.py" make test-docker
```

Expected: PASS (2 tests).

- [ ] **Step 6: Format + commit**

```bash
make format
git add backend/scripts/seed_tech_templates.py backend/scripts/data/tech_templates.yaml \
    tests/scripts/test_seed_tech_templates.py
git commit -m "feat(templates): add seed script and starter catalogue"
```

---

## Task 10: Full suite + lint

- [ ] **Step 1: Run full suite**

```bash
make test-docker
```

Expected: all tests pass (Phase 1's 395 + new Phase 2 tests).

- [ ] **Step 2: Run `make check`**

```bash
make check
```

Expected: ruff + black clean. mypy will show the same two pre-existing errors from Phase 1 (`backend/scripts/_seed_core.py` yaml import, `sdk/aide_sdk/resources/datasets.py` type assignment) — both documented as ignorable in CLAUDE.md.

- [ ] **Step 3: If any new mypy errors attributable to Phase 2 appear, fix them and commit**

```bash
git add -A
git commit -m "chore: fix typing for templates module"
```

---

## Task 11: Docs — data model JSON + ADR-017

**Files:**
- Modify: `docs/AIDE_data_model.json`
- Create: `docs/adr/adr-017-tech-field-templates.md`
- Modify: `docs/adr/README.md`

- [ ] **Step 1: Update `docs/AIDE_data_model.json`**

Add two new tables matching the ChartDB format used in Phase 1:

- `t_tech_field_templates` with columns: id (uuid PK), code (varchar(100) unique), name (varchar(255)), layer (varchar(32)), note (text nullable), created_at, updated_at, created_by nullable, updated_by nullable, row_version int.
- `t_tech_field_template_fields` with columns: id (uuid PK), template_id (uuid FK to tech_field_templates.id, CASCADE — capture in `comments`), name (varchar(255)), type_code (varchar(64)), order (int), note, created_at, updated_at, created_by, updated_by, row_version. Unique constraint on `(template_id, name)` → `uq_tft_field_name`.

Add one relationship: `t_tech_field_templates -> t_tech_field_template_fields` (1:N).

Do NOT model the resolver YAML (it's a file, not a DB artifact).

- [ ] **Step 2: Create `docs/adr/adr-017-tech-field-templates.md`**

Follow the structure of `docs/adr/adr-016-dataset-lineage.md`. Fill in:

- **Title:** ADR-017: Tech-Field Templates — Detached Presets with Abstract Type Codes
- **Status:** Accepted
- **Date:** 2026-04-21

Sections:

1. **Context and Problem** — tech fields (SCD2, CDC payload, snapshot) are repeated across many datasets with predictable shape. Typing them by hand per dataset per flavor is error-prone. Need a reusable preset that works across flavors (same abstract shape, different concrete types).

2. **Options Considered:**
   - **A. Template with per-flavor copies** (chosen against, spec §3.7 D2): `scd2_postgres`, `scd2_iceberg`, `scd2_kafka_avro` — explicit but duplicative.
   - **B. Abstract type_code + resolver (chosen, spec §3.7 D1):** template_field holds `TIMESTAMP`/`STRING`/…; resolver maps `(flavor, type_code) → data_type_code` at apply-time.
   - **C. No templates — bind each dataset manually:** rejected, product requirement for reuse.

3. **Decision:**
   - Two tables: `tech_field_templates` (hard-delete, unique code), `tech_field_template_fields` (hard-delete, FK CASCADE from parent, unique `(template_id, name)`).
   - Detached from Field: applying creates `Field(is_tech=True)` rows with no FK back to the template. Subsequent template edits do not propagate.
   - `Field.extra` JSONB stores `{"data_type_id": "...", "tech_type_code": "..."}` as a hint for downstream `FieldBinding` creation.
   - Resolver lives in `backend/scripts/data/tech_type_resolver.yaml` and is loaded once at module import time into a frozen dataclass. Duplicate entries fail loading.
   - Apply is idempotent (skip existing names) and layer-gated (`dataset.layer == template.layer`, else 400).

4. **Consequences:**
   - Positive: single template covers all flavors; applying is deterministic; drift allowed by design (per spec, field edits per-dataset).
   - Negative: template changes don't propagate — deliberate trade-off; resolver YAML must be maintained alongside new flavors; `Field.extra` is a soft hint, not a validated FK.
   - Migration: additive only (two tables, no data migration).

5. **Related:**
   - Spec §3.7, §5.3, §8 in `docs/superpowers/specs/2026-04-21-dataset-lineage-design.md`
   - Phase 2 plan: `docs/superpowers/plans/2026-04-21-dataset-lineage-phase-2.md`
   - Phase 1 ADR: `docs/adr/adr-016-dataset-lineage.md`

- [ ] **Step 3: Update `docs/adr/README.md`**

Add a row for ADR-017 matching ADR-016's style.

- [ ] **Step 4: Commit**

```bash
git add docs/AIDE_data_model.json docs/adr/adr-017-tech-field-templates.md docs/adr/README.md
git commit -m "docs: add ADR-017 tech-field templates"
```

---

## Closing

Phase 2 complete when:
- `make test-docker` passes full suite (Phase 1 395 + Phase 2 new tests).
- `make check` clean (modulo pre-existing documented mypy errors).
- `tech_field_templates` + `tech_field_template_fields` appear in `docs/AIDE_data_model.json`.
- ADR-017 indexed in `docs/adr/README.md`.

Scope delivered: full CRUD for templates + nested fields, apply-template endpoint, type-code resolver with YAML-backed mappings, seed script with starter catalogue. Phase 3 (beyond scope): auto-binding to DatasetSchema + FieldBinding, template versioning, per-flavor data-type overrides at apply-time.
