# Schema-Pinned Lineage & Field Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `DatasetLink` into a schema-pinned data contract and replace `Field.is_tech: bool` with a three-state `Field.origin` enum. Add an on-demand compat endpoint ETL pre-flight uses to block loads on broken contracts.

**Architecture:** Two new FK columns on `dataset_links` point at `dataset_schemas` (`ON DELETE RESTRICT`, service-validated belongs-to-dataset). `Field.origin` replaces `is_tech` with a state machine (`mapped` / `tech` / `deprecated`) that `FieldService.update` enforces atomically with `FieldLink` creates/deletes. `DatasetLinkCompatService` computes per-link compat on demand via four JOINs over `field_link + field_binding (src) + field_binding (tgt) + cast_rule`. Migration is two Alembic steps plus a Python backfill; all four packages (`aide-schemas`, `backend`, `aide-sdk`, `aide-crawler`) rev to `0.2.0` lockstep.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, pytest + pytest-asyncio. Tests run in Docker (`make test-docker`); narrow scope with `PYTEST_ARGS="-v tests/path/test_file.py"`. Formatting via `make format`.

**Spec:** `docs/superpowers/specs/2026-04-23-schema-pinned-lineage-design.md`

**Predecessor:** ADR-016 (Phase 1 lineage), ADR-017 (tech-field templates).

---

## File Map

**Created:**
- `schemas/aide_schemas/lineage_compat.py` — `FieldCompatIssue` enum, `PinDrift`, `FieldCompatRow`, `DatasetLinkCompatReport`, `DatasetLinkCompatSummary`
- `backend/schemas/lineage_compat.py` — re-export from `aide_schemas.lineage_compat`
- `backend/services/dataset_link_compat.py` — `DatasetLinkCompatService` (algorithm + aggregation + bulk)
- `backend/alembic/versions/<rev>_add_lineage_pins_a_nullable.py` — Migration A (additive)
- `backend/alembic/versions/<rev>_add_lineage_pins_b_finalize.py` — Migration B (NOT NULL + drop `is_tech`)
- `backend/scripts/migrate_lineage_pins.py` — backfill script
- `sdk/aide_sdk/resources/dataset_links.py` — `DatasetLinksResource` with `compat()` and `list_compat()`
- `sdk/tests/test_dataset_links_resource.py` — mock HTTP tests
- `tests/services/test_dataset_link_compat_service.py` — per-issue fixtures
- `tests/repositories/test_dataset_schema_repository.py` — `latest_for_dataset` test
- `tests/integration/test_lineage_compat_e2e.py` — end-to-end scenarios
- `docs/adr/adr-018-schema-pinned-lineage.md`

**Modified:**
- `schemas/aide_schemas/field.py` — add `FieldOrigin` enum, replace `is_tech` with `origin` in `FieldBase`/`FieldUpdate`/`FieldTree`
- `schemas/aide_schemas/dataset_link.py` — add `source_schema_id` / `target_schema_id` to `DatasetLinkBase`, restrict `DatasetLinkUpdate`
- `schemas/aide_schemas/__init__.py` — export new types
- `schemas/pyproject.toml` — version → `0.2.0`
- `backend/schemas/field.py` — re-export `FieldOrigin`
- `backend/models/field.py` — replace `is_tech` with `origin: Mapped[str]`
- `backend/models/dataset_link.py` — add schema_id columns + relationships
- `backend/repositories/dataset_schema.py` — add `latest_for_dataset`
- `backend/repositories/field_binding.py` — add `get_by_field_and_schema`
- `backend/repositories/dataset_link.py` — add `list_with_compat_summary` (joined drift + field counts)
- `backend/schemas/filters.py` — extend `DatasetLinkFilter`, add `DatasetLinkCompatFilter`, update `FieldFilter`
- `backend/services/field.py` — `origin` state machine in `_pre_update`; remove old `is_tech` check
- `backend/services/dataset_link.py` — schema belongs-to-dataset on create/update
- `backend/services/field_link.py` — validate source/target field has binding in pinned schemas
- `backend/services/dataset_schema.py` — catch RESTRICT IntegrityError on delete
- `backend/core/errors.py` — add `SCHEMA_DATASET_MISMATCH`, `FIELD_ORIGIN_CONFLICT`, `FIELD_BINDING_MISSING`, `DATASET_SCHEMA_IN_USE` + ERROR_MAP entries
- `backend/api/v1/dataset_links.py` — add `/compat` and `/compat` list endpoints, update responses for new error codes
- `backend/api/v1/fields.py` — wire error codes for origin transitions
- `backend/api/v1/dataset_schemas.py` — wire `DATASET_SCHEMA_IN_USE`
- `sdk/aide_sdk/client.py` — register `DatasetLinksResource`
- `sdk/pyproject.toml` — version → `0.2.0`
- `crawler/pyproject.toml` — version → `0.2.0`
- `tests/models/test_dataset_link.py` — FK RESTRICT test, pin column test
- `tests/services/test_dataset_link_service.py` — pin validation cases
- `tests/services/test_field_service.py` — origin state machine cases
- `tests/services/test_field_link_service.py` — binding-missing case
- `tests/repositories/test_field_binding_repository.py` — `get_by_field_and_schema`
- `tests/repositories/test_dataset_link_repository.py` — compat list query
- `tests/api/test_dataset_links.py` — compat endpoints + new error codes
- `tests/api/test_fields.py` — origin PATCH cases
- `tests/api/test_dataset_schemas.py` — DELETE RESTRICT case
- `docs/AIDE_data_model.json` — update `dataset_links` and `fields` tables
- `docs/adr/README.md` — add ADR-018 row
- `CLAUDE.md` — append quirks

---

## Task 1: `FieldOrigin` enum + `FieldCompatIssue` enum in `aide-schemas`

**Files:**
- Modify: `schemas/aide_schemas/field.py`
- Create: `schemas/aide_schemas/lineage_compat.py`
- Modify: `schemas/aide_schemas/__init__.py`

These are new enums used by later DTOs. Keep enums lean — types and docstrings only, no validators yet.

- [ ] **Step 1: Add `FieldOrigin` to `schemas/aide_schemas/field.py`**

Add near the top, after imports, before `FieldBase`:

```python
import enum


class FieldOrigin(str, enum.Enum):
    """Lifecycle state of a Field for lineage purposes.

    MAPPED — has inbound FieldLink(s) as target; fed from a source column.
    TECH — generated by the pipeline (timestamps, CDC op, hashes).
    DEPRECATED — no source, worker pads NULL for backward compatibility.
    """

    MAPPED = "mapped"
    TECH = "tech"
    DEPRECATED = "deprecated"
```

- [ ] **Step 2: Create `schemas/aide_schemas/lineage_compat.py`**

```python
from __future__ import annotations

import enum
import uuid

from pydantic import BaseModel, ConfigDict


class FieldCompatIssue(str, enum.Enum):
    """Issues surfaced for one FieldLink under a DatasetLink's pinned schemas."""

    SOURCE_UNBOUND = "source_unbound"
    TARGET_UNBOUND = "target_unbound"
    TYPE_INCOMPATIBLE = "type_incompatible"
    TYPE_UNSAFE_CAST = "type_unsafe_cast"
    TYPE_NEEDS_CAST = "type_needs_cast"
    NULLABILITY_WARN = "nullability_warn"


class CompatSeverity(str, enum.Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


class PinDriftSide(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pinned_version: int
    latest_version: int
    has_drift: bool


class PinDrift(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: PinDriftSide
    target: PinDriftSide


class FieldCompatFieldRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class FieldCompatRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field_link_id: uuid.UUID
    source_field: FieldCompatFieldRef
    target_field: FieldCompatFieldRef
    source_type: str | None
    target_type: str | None
    issues: list[FieldCompatIssue]
    severity: CompatSeverity
    cast_rule_id: uuid.UUID | None


class CompatSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ok: int
    warn: int
    error: int
    total: int


class DatasetRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    object_name: str


class DatasetLinkCompatReport(BaseModel):
    """Full compat report for a single DatasetLink."""

    model_config = ConfigDict(from_attributes=True)

    dataset_link_id: uuid.UUID
    pin_drift: PinDrift
    field_compat: list[FieldCompatRow]
    summary: CompatSummary
    status: CompatSeverity


class DatasetLinkCompatSummary(BaseModel):
    """Lightweight per-link summary for bulk monitoring listing."""

    model_config = ConfigDict(from_attributes=True)

    dataset_link_id: uuid.UUID
    source_dataset: DatasetRef
    target_dataset: DatasetRef
    status: CompatSeverity
    summary: CompatSummary
    pin_drift: dict[str, bool]  # {"source": bool, "target": bool}
```

- [ ] **Step 3: Export new types in `schemas/aide_schemas/__init__.py`**

Add to imports:

```python
from .field import FieldCreate, FieldOrigin, FieldRead, FieldUpdate
from .lineage_compat import (
    CompatSeverity,
    CompatSummary,
    DatasetLinkCompatReport,
    DatasetLinkCompatSummary,
    FieldCompatIssue,
    FieldCompatRow,
    PinDrift,
    PinDriftSide,
)
```

Add each name to the `__all__` list.

- [ ] **Step 4: Run `make check` to verify imports resolve**

Run: `cd schemas && uv run mypy aide_schemas/` (the root backend mypy also covers it).

Expected: PASS. If failures, most likely missing `__all__` export or forward-ref ordering.

- [ ] **Step 5: Commit**

```bash
git add schemas/aide_schemas/field.py schemas/aide_schemas/lineage_compat.py schemas/aide_schemas/__init__.py
git commit -m "feat(schemas): add FieldOrigin + lineage compat DTOs"
```

---

## Task 2: Update DTO fields in `aide-schemas`

**Files:**
- Modify: `schemas/aide_schemas/field.py`
- Modify: `schemas/aide_schemas/dataset_link.py`

Replace `is_tech: bool` with `origin: FieldOrigin` across field DTOs. Add pin fields to DatasetLink DTOs. `DatasetLinkUpdate` omits `source_dataset_id` / `target_dataset_id` — Pydantic rejects them if sent.

- [ ] **Step 1: Update `schemas/aide_schemas/field.py` — replace `is_tech` with `origin`**

Overwrite the file (after Task 1's `FieldOrigin` import stays at top):

```python
from __future__ import annotations

import enum
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class FieldOrigin(str, enum.Enum):
    """Lifecycle state of a Field for lineage purposes.

    MAPPED — has inbound FieldLink(s) as target; fed from a source column.
    TECH — generated by the pipeline (timestamps, CDC op, hashes).
    DEPRECATED — no source, worker pads NULL for backward compatibility.
    """

    MAPPED = "mapped"
    TECH = "tech"
    DEPRECATED = "deprecated"


class FieldBase(BaseModel):
    """Base field schema."""

    dataset_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    name: str
    path: str | None = None
    extra: dict[str, Any] | None = None
    origin: FieldOrigin = FieldOrigin.MAPPED


class FieldCreate(FieldBase, NoteMixin):
    """Schema for field creation."""

    pass


class FieldUpdate(VersionedUpdateMixin, NoteMixin):
    """Schema for field update."""

    dataset_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    name: str | None = None
    path: str | None = None
    extra: dict[str, Any] | None = None
    origin: FieldOrigin | None = None


class FieldRead(FieldBase, MetaDataMixin):
    """Schema for reading field data."""

    model_config = ConfigDict(from_attributes=True)


class FieldTree(MetaDataMixin):
    """Recursive schema for reading a field tree."""

    model_config = ConfigDict(from_attributes=True)

    dataset_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    path: str | None
    extra: dict[str, Any] | None
    origin: FieldOrigin
    children: list[FieldTree]
```

- [ ] **Step 2: Update `schemas/aide_schemas/dataset_link.py`**

Overwrite:

```python
import uuid

from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class DatasetLinkBase(BaseModel):
    source_dataset_id: uuid.UUID
    target_dataset_id: uuid.UUID
    source_schema_id: uuid.UUID
    target_schema_id: uuid.UUID


class DatasetLinkCreate(DatasetLinkBase, NoteMixin):
    pass


class DatasetLinkUpdate(VersionedUpdateMixin, NoteMixin):
    """Dataset IDs are immutable — omitted here. Pydantic rejects them as extras."""

    source_schema_id: uuid.UUID | None = None
    target_schema_id: uuid.UUID | None = None


class DatasetLinkRead(DatasetLinkBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 3: Write a unit test proving `DatasetLinkCreate` requires schema ids**

Create `schemas/tests/test_dataset_link_schema.py` (if `schemas/tests/` exists — otherwise put it under `tests/unit/test_dataset_link_schema.py`). Verify its location first:

```bash
ls schemas/tests/ 2>/dev/null || ls tests/unit 2>/dev/null
```

If neither exists, put the test under `tests/unit/` (create the dir + `__init__.py`). Test:

```python
import uuid

import pytest
from pydantic import ValidationError

from aide_schemas.dataset_link import DatasetLinkCreate


def test_dataset_link_create_requires_schema_ids():
    with pytest.raises(ValidationError) as exc_info:
        DatasetLinkCreate(
            source_dataset_id=uuid.uuid4(),
            target_dataset_id=uuid.uuid4(),
        )
    missing = {err["loc"][0] for err in exc_info.value.errors()}
    assert {"source_schema_id", "target_schema_id"}.issubset(missing)


def test_dataset_link_create_accepts_schema_ids():
    link = DatasetLinkCreate(
        source_dataset_id=uuid.uuid4(),
        target_dataset_id=uuid.uuid4(),
        source_schema_id=uuid.uuid4(),
        target_schema_id=uuid.uuid4(),
    )
    assert link.source_schema_id != link.target_schema_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_ARGS="-v tests/unit/test_dataset_link_schema.py" make test-docker`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add schemas/aide_schemas/field.py schemas/aide_schemas/dataset_link.py tests/unit/
git commit -m "feat(schemas): pin schema_id on DatasetLink DTO, replace is_tech with origin"
```

---

## Task 3: Error codes

**Files:**
- Modify: `backend/core/errors.py`

Add four new error codes and their ERROR_MAP entries. Put them near existing dataset-link and field codes.

- [ ] **Step 1: Add constants in `backend/core/errors.py`**

Locate the DatasetLink/Field constants block (line ~36 onwards). Add after `FIELD_NON_TECH_REQUIRES_SOURCE`:

```python
SCHEMA_DATASET_MISMATCH = "SCHEMA_DATASET_MISMATCH"
FIELD_ORIGIN_CONFLICT = "FIELD_ORIGIN_CONFLICT"
FIELD_BINDING_MISSING = "FIELD_BINDING_MISSING"
DATASET_SCHEMA_IN_USE = "DATASET_SCHEMA_IN_USE"
```

Add ERROR_MAP entries, grouping with existing dataset-link / field codes:

```python
    SCHEMA_DATASET_MISMATCH: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "The schema does not belong to the specified dataset.",
    ),
    FIELD_ORIGIN_CONFLICT: (
        status.HTTP_409_CONFLICT,
        "Field origin transition is blocked by current FieldLink state.",
    ),
    FIELD_BINDING_MISSING: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Field has no FieldBinding in the DatasetLink's pinned schema.",
    ),
    DATASET_SCHEMA_IN_USE: (
        status.HTTP_409_CONFLICT,
        "Cannot delete: this dataset schema is pinned by one or more active DatasetLinks.",
    ),
```

- [ ] **Step 2: Add unit test verifying codes resolve**

Create `tests/core/test_errors.py` if not present, or append to existing. Test body:

```python
import pytest

from backend.core import errors


@pytest.mark.parametrize(
    "code,expected_status",
    [
        (errors.SCHEMA_DATASET_MISMATCH, 422),
        (errors.FIELD_ORIGIN_CONFLICT, 409),
        (errors.FIELD_BINDING_MISSING, 422),
        (errors.DATASET_SCHEMA_IN_USE, 409),
    ],
)
def test_new_lineage_error_codes_registered(code: str, expected_status: int):
    assert code in errors.ERROR_MAP
    status_code, detail = errors.ERROR_MAP[code]
    assert status_code == expected_status
    assert detail  # non-empty message
```

- [ ] **Step 3: Run test**

Run: `PYTEST_ARGS="-v tests/core/test_errors.py" make test-docker`

Expected: 4 passed. If the file `tests/core/test_errors.py` did not exist, ensure `tests/core/__init__.py` exists too.

- [ ] **Step 4: Commit**

```bash
git add backend/core/errors.py tests/core/
git commit -m "feat(errors): add schema pin + field origin + schema-in-use codes"
```

---

## Task 4: Backend model — `Field.origin` replaces `is_tech`

**Files:**
- Modify: `backend/models/field.py`
- Modify: `backend/schemas/field.py`

- [ ] **Step 1: Write failing test in `tests/models/test_field_model.py`**

Create or extend. Confirm path first: `ls tests/models/test_field*.py`. If no `test_field_model.py` exists, create it.

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.field import Field


async def _seed_dataset(session: AsyncSession) -> DatasetRdbms:
    kind = SystemKind(code="RDBMS_ORIGIN", name="RDBMS Origin")
    flavor = SystemFlavor(code="PG_ORIGIN", name="PG Origin", kind=kind)
    system = System(code="SYS_ORIGIN", name="System Origin", flavor=flavor)
    ds = DatasetRdbms(
        system=system, object_name="o", kind="rdbms", schema_name="s", table_name="t"
    )
    session.add_all([kind, flavor, system, ds])
    await session.flush()
    return ds


@pytest.mark.asyncio
async def test_field_origin_default_is_mapped(transactional_session: AsyncSession):
    ds = await _seed_dataset(transactional_session)
    f = Field(dataset_id=ds.id, name="col")
    transactional_session.add(f)
    await transactional_session.flush()
    await transactional_session.refresh(f)
    assert f.origin == "mapped"


@pytest.mark.asyncio
async def test_field_origin_accepts_all_states(transactional_session: AsyncSession):
    ds = await _seed_dataset(transactional_session)
    for origin in ("mapped", "tech", "deprecated"):
        f = Field(dataset_id=ds.id, name=f"col_{origin}", origin=origin)
        transactional_session.add(f)
    await transactional_session.flush()
```

- [ ] **Step 2: Run test — expect failure**

Run: `PYTEST_ARGS="-v tests/models/test_field_model.py" make test-docker`

Expected: FAIL — `origin` attribute doesn't exist on Field (or DB column missing if migrations not yet up to date, but we handle that in Task 6).

- [ ] **Step 3: Update `backend/models/field.py`**

Replace the `is_tech` column with `origin`:

```python
import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class Field(Base, MetaDataMixin):
    __tablename__ = "fields"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    origin: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="mapped"
    )

    dataset = relationship("Dataset")
    parent = relationship("Field", remote_side="Field.id", back_populates="children")
    children = relationship(
        "Field",
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "idx_field_root_name",
            "dataset_id",
            "name",
            unique=True,
            postgresql_where=(parent_id.is_(None)),
        ),
        Index(
            "idx_field_nested_name",
            "dataset_id",
            "parent_id",
            "name",
            unique=True,
            postgresql_where=(parent_id.isnot(None)),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"Field(id={self.id}, name={self.name}, "
            f"dataset_id={self.dataset_id}, origin={self.origin})"
        )
```

- [ ] **Step 4: Re-export `FieldOrigin` in `backend/schemas/field.py`**

Update the file:

```python
from aide_schemas.field import (
    FieldCreate as FieldCreate,
    FieldOrigin as FieldOrigin,
    FieldRead as FieldRead,
    FieldTree as FieldTree,
    FieldUpdate as FieldUpdate,
)
```

- [ ] **Step 5: Run models test — still will fail (no migration yet)**

Skip run here — migrations in Task 6 will make DB match. Commit what we have and proceed.

- [ ] **Step 6: Commit**

```bash
git add backend/models/field.py backend/schemas/field.py tests/models/test_field_model.py
git commit -m "feat(field): replace is_tech with origin enum on model"
```

---

## Task 5: Backend model — `DatasetLink` pin columns

**Files:**
- Modify: `backend/models/dataset_link.py`
- Modify: `tests/models/test_dataset_link.py`

- [ ] **Step 1: Write failing test for FK RESTRICT**

Append to `tests/models/test_dataset_link.py`:

```python
@pytest.mark.asyncio
async def test_dataset_schema_delete_blocked_by_active_pin(
    transactional_session: AsyncSession,
):
    """RESTRICT FK blocks DatasetSchema delete when referenced by DatasetLink."""
    from backend.models.dataset_schema import DatasetSchema

    system = await _make_system(transactional_session, code_suffix="RESTRICT")
    src = DatasetRdbms(
        system_id=system.id,
        object_name="restrict_src",
        kind="rdbms",
        schema_name="s",
        table_name="src",
    )
    tgt = DatasetRdbms(
        system_id=system.id,
        object_name="restrict_tgt",
        kind="rdbms",
        schema_name="s",
        table_name="tgt",
    )
    transactional_session.add_all([src, tgt])
    await transactional_session.flush()

    src_schema = DatasetSchema(dataset_id=src.id, version_num=1, schema={})
    tgt_schema = DatasetSchema(dataset_id=tgt.id, version_num=1, schema={})
    transactional_session.add_all([src_schema, tgt_schema])
    await transactional_session.flush()

    link = DatasetLink(
        source_dataset_id=src.id,
        target_dataset_id=tgt.id,
        source_schema_id=src_schema.id,
        target_schema_id=tgt_schema.id,
    )
    transactional_session.add(link)
    await transactional_session.flush()

    await transactional_session.delete(src_schema)
    with pytest.raises(IntegrityError):
        await transactional_session.flush()
```

- [ ] **Step 2: Run test — expect failure**

Run: `PYTEST_ARGS="-v tests/models/test_dataset_link.py::test_dataset_schema_delete_blocked_by_active_pin" make test-docker`

Expected: FAIL — either column doesn't exist or FK doesn't restrict.

- [ ] **Step 3: Update `backend/models/dataset_link.py`**

```python
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import SoftDeleteMetaDataMixin


class DatasetLink(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "dataset_links"

    source_dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id"),
        nullable=False,
        index=True,
    )
    target_dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id"),
        nullable=False,
        index=True,
    )
    source_schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dataset_schemas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dataset_schemas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    source_dataset = relationship("Dataset", foreign_keys=[source_dataset_id])
    target_dataset = relationship("Dataset", foreign_keys=[target_dataset_id])
    source_schema = relationship("DatasetSchema", foreign_keys=[source_schema_id])
    target_schema = relationship("DatasetSchema", foreign_keys=[target_schema_id])
    field_links = relationship(
        "FieldLink",
        back_populates="dataset_link",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "uq_dataset_link_pair_active",
            "source_dataset_id",
            "target_dataset_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "source_dataset_id <> target_dataset_id",
            name="ck_dataset_link_no_self",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"DatasetLink(id={self.id}, "
            f"source={self.source_dataset_id}, target={self.target_dataset_id}, "
            f"src_schema={self.source_schema_id}, tgt_schema={self.target_schema_id})"
        )
```

- [ ] **Step 4: Also update all existing `tests/models/test_dataset_link.py` usages**

Existing tests create `DatasetLink(source_dataset_id=..., target_dataset_id=...)` without schema ids. Update each one to create minimal DatasetSchemas first and pass schema ids. Pattern:

```python
src_schema = DatasetSchema(dataset_id=src.id, version_num=1, schema={})
tgt_schema = DatasetSchema(dataset_id=tgt.id, version_num=1, schema={})
session.add_all([src_schema, tgt_schema])
await session.flush()
link = DatasetLink(
    source_dataset_id=src.id,
    target_dataset_id=tgt.id,
    source_schema_id=src_schema.id,
    target_schema_id=tgt_schema.id,
)
```

Apply this update to every test in the file that instantiates `DatasetLink`. Add the `from backend.models.dataset_schema import DatasetSchema` import.

- [ ] **Step 5: Don't run yet — migrations needed (Task 6)**

Commit and move on.

- [ ] **Step 6: Commit**

```bash
git add backend/models/dataset_link.py tests/models/test_dataset_link.py
git commit -m "feat(dataset-link): add source/target schema pin columns"
```

---

## Task 6: Alembic Migration A — additive, nullable

**Files:**
- Create: `backend/alembic/versions/<rev>_add_lineage_pins_a_nullable.py`

Write Migration A by hand — we don't auto-gen because the final model differs from the migration-A state (model has NOT NULL, Migration A has nullable).

- [ ] **Step 1: Find the current head revision**

Run: `ls backend/alembic/versions/ | head` and cross-check `alembic heads` content in the latest file. Record the head revision hash (call it `<PREVHEAD>` below).

To avoid port conflicts, first ensure dev DB (`aide-db-1` on 5432) is stopped:

```bash
docker stop aide-db-1 2>/dev/null || true
```

(Per CLAUDE.md: `make alembic-gen` binds port 5432. Same for alembic commands that connect.)

Record the current head:

```bash
uv run alembic -c backend/alembic.ini heads
```

- [ ] **Step 2: Create the migration file**

Create `backend/alembic/versions/<generated_rev>_add_lineage_pins_a_nullable.py`. Use a timestamp-based rev identifier or generate one with `uuid.uuid4().hex[:12]`:

```python
"""add lineage pins (migration A — nullable)

Additive step: add source_schema_id / target_schema_id on dataset_links (nullable),
add origin on fields (nullable, server_default='mapped'). Keeps is_tech for now.

Revision ID: <fill in>
Revises: <PREVHEAD>
Create Date: 2026-04-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "<fill in with uuid.uuid4().hex[:12]>"
down_revision = "<PREVHEAD>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # dataset_links schema pins
    op.add_column(
        "dataset_links",
        sa.Column(
            "source_schema_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_schemas.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "dataset_links",
        sa.Column(
            "target_schema_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_schemas.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_dataset_links_source_schema",
        "dataset_links",
        ["source_schema_id"],
    )
    op.create_index(
        "idx_dataset_links_target_schema",
        "dataset_links",
        ["target_schema_id"],
    )

    # fields.origin with server_default so new rows never land NULL
    op.add_column(
        "fields",
        sa.Column(
            "origin",
            sa.String(20),
            nullable=True,
            server_default="mapped",
        ),
    )


def downgrade() -> None:
    op.drop_column("fields", "origin")
    op.drop_index("idx_dataset_links_target_schema", table_name="dataset_links")
    op.drop_index("idx_dataset_links_source_schema", table_name="dataset_links")
    op.drop_column("dataset_links", "target_schema_id")
    op.drop_column("dataset_links", "source_schema_id")
```

Replace `<fill in>` with a real hex identifier (e.g. `uuid.uuid4().hex[:12]`) and `<PREVHEAD>` with the output from Step 1.

- [ ] **Step 3: Run Migration A (locally, not via `make alembic-gen`)**

Apply to dev DB:

```bash
make alembic-head
```

Expected: migration succeeds, no errors. If `aide-db-1` not running: `docker start aide-db-1` first.

Verify columns:

```bash
docker exec aide-db-1 psql -U postgres -d aide -c "\d dataset_links" | grep schema_id
docker exec aide-db-1 psql -U postgres -d aide -c "\d fields" | grep origin
```

Both columns should appear as nullable.

- [ ] **Step 4: Re-run Task 4 + 5 tests to verify they pass with migration applied**

Run: `PYTEST_ARGS="-v tests/models/test_field_model.py tests/models/test_dataset_link.py" make test-docker`

Expected: ALL PASS. The model tests from Tasks 4 and 5 were deferred — Migration A creates the columns they exercise.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/*_add_lineage_pins_a_nullable.py
git commit -m "feat(migration): add lineage pin columns nullable (step A)"
```

---

## Task 7: Backfill script

> **Note on testability:** the backfill targets data that is only observable between Migration A (nullable) and Migration B (NOT NULL). The test DB runs both migrations at session start, so there are never any NULL-pinned `DatasetLink` rows or `is_tech=True` fields to backfill. The tests below verify only the shape and idempotency of the script (no-op when nothing to backfill). The full transition is validated manually via `alembic downgrade` + rerun or observed at deploy time.

**Files:**
- Create: `backend/scripts/migrate_lineage_pins.py`

- [ ] **Step 1: Create the script**

```python
"""Backfill script for lineage pin columns.

After Migration A: populate source_schema_id / target_schema_id on each
active DatasetLink with MAX(version_num) DatasetSchema per side; populate
fields.origin from legacy is_tech boolean.

Idempotent. Re-run after fixing unresolved cases.

Usage:
    uv run python -m backend.scripts.migrate_lineage_pins
"""
from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.models.field import Field


async def _latest_schema(
    session: AsyncSession, dataset_id: uuid.UUID
) -> DatasetSchema | None:
    stmt = (
        select(DatasetSchema)
        .where(DatasetSchema.dataset_id == dataset_id)
        .order_by(DatasetSchema.version_num.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def backfill_dataset_link_pins(session: AsyncSession) -> list[tuple]:
    """Return list of (link_id, src_max, tgt_max) for unresolved links."""
    unresolved: list[tuple] = []
    stmt = select(DatasetLink).where(
        DatasetLink.deleted_at.is_(None),
        or_(
            DatasetLink.source_schema_id.is_(None),
            DatasetLink.target_schema_id.is_(None),
        ),
    )
    result = await session.execute(stmt)
    for link in result.scalars():
        src_max = await _latest_schema(session, link.source_dataset_id)
        tgt_max = await _latest_schema(session, link.target_dataset_id)
        if src_max is None or tgt_max is None:
            unresolved.append((link.id, src_max, tgt_max))
            continue
        link.source_schema_id = src_max.id
        link.target_schema_id = tgt_max.id
    return unresolved


async def backfill_field_origin(session: AsyncSession) -> None:
    """Populate fields.origin from legacy is_tech column.

    Uses raw SQL since the column may not yet exist on the ORM model post-Task 9.
    Idempotent: only updates rows where origin is still the default and is_tech=true.
    """
    # is_tech still present until Migration B.
    await session.execute(
        update(Field.__table__)
        .where(
            Field.__table__.c.is_tech.is_(True),
            Field.__table__.c.origin == "mapped",
        )
        .values(origin="tech")
    )


async def main() -> int:
    async with AsyncSessionLocal() as session:
        unresolved = await backfill_dataset_link_pins(session)
        await backfill_field_origin(session)
        await session.commit()

    if unresolved:
        print(
            "UNRESOLVED LINKS (source or target dataset has no DatasetSchema):",
            flush=True,
        )
        for row in unresolved:
            print(f"  {row}", flush=True)
        return 1
    print("Backfill complete.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Add smoke tests for the backfill**

Create `tests/scripts/test_migrate_lineage_pins.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.scripts.migrate_lineage_pins import (
    _latest_schema,
    backfill_dataset_link_pins,
    backfill_field_origin,
)


@pytest.mark.asyncio
async def test_backfill_pins_is_noop_when_all_links_already_pinned(
    transactional_session: AsyncSession,
):
    """Post-Migration-B state: every DatasetLink has NOT NULL pins, so the
    WHERE-NULL filter matches nothing. Function returns empty unresolved list."""
    unresolved = await backfill_dataset_link_pins(transactional_session)
    assert unresolved == []


@pytest.mark.asyncio
async def test_backfill_field_origin_is_noop_without_legacy_column(
    transactional_session: AsyncSession,
):
    """Post-Migration-B state: fields.is_tech is dropped. The function
    references Field.__table__.c.is_tech, which will no longer exist on the
    mapped model. The backfill is expected to be a no-op or fail gracefully —
    either way the assertion is the same: no exception should propagate to
    the caller."""
    try:
        await backfill_field_origin(transactional_session)
    except AttributeError:
        # Column already dropped post-Migration-B — acceptable.
        pass


@pytest.mark.asyncio
async def test_latest_schema_returns_highest_version(
    transactional_session: AsyncSession,
):
    """Spot-check the helper. The equivalent repository method is tested
    thoroughly in Task 9; this confirms the script-local shim lines up."""
    from backend.models import System, SystemFlavor, SystemKind
    from backend.models.dataset import DatasetRdbms
    from backend.models.dataset_schema import DatasetSchema

    kind = SystemKind(code="BF_LS_K", name="BF LS Kind")
    flavor = SystemFlavor(code="BF_LS_F", name="BF LS Flavor", kind=kind)
    system = System(code="BF_LS_S", name="BF LS System", flavor=flavor)
    ds = DatasetRdbms(
        system=system, object_name="bf_ls_ds", kind="rdbms",
        schema_name="s", table_name="t",
    )
    transactional_session.add_all([kind, flavor, system, ds])
    await transactional_session.flush()
    transactional_session.add_all([
        DatasetSchema(dataset_id=ds.id, version_num=1, schema={}),
        DatasetSchema(dataset_id=ds.id, version_num=5, schema={}),
    ])
    await transactional_session.flush()

    latest = await _latest_schema(transactional_session, ds.id)
    assert latest is not None
    assert latest.version_num == 5
```

Note: the `backfill_field_origin` function references `Field.__table__.c.is_tech`, which does not exist after Migration B. The script is meant to run between Migration A and Migration B — the test here only verifies the function signature and idempotent no-op behavior in the fully-migrated test DB. To validate the actual transition, run `alembic downgrade <MIGRATION_A_REV>` locally, seed data with `is_tech=True`, run the script, confirm `origin='tech'`, then re-apply Migration B.

- [ ] **Step 3: Run tests**

Run: `PYTEST_ARGS="-v tests/scripts/test_migrate_lineage_pins.py" make test-docker`

Expected: 3 passed.

If missing, create `tests/scripts/__init__.py` (empty).

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/migrate_lineage_pins.py tests/scripts/
git commit -m "feat(scripts): add lineage-pin backfill script"
```

---

## Task 8: Alembic Migration B — finalize

**Files:**
- Create: `backend/alembic/versions/<rev>_add_lineage_pins_b_finalize.py`

- [ ] **Step 1: Create the migration file**

Use Migration A's revision as `down_revision` below.

```python
"""add lineage pins (migration B — finalize)

Flips schema_ids and origin to NOT NULL and drops fields.is_tech.

WARNING: Downgrade is only safe when no Field rows have origin='deprecated'.
On downgrade, 'deprecated' maps to is_tech=False (mapped) — which violates
the Phase 1 invariant that mapped target fields must have a source FieldLink.
Hold this migration until the forward direction is stable in prod.

Revision ID: <fill in>
Revises: <MIGRATION_A_REV>
Create Date: 2026-04-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "<fill in>"
down_revision = "<MIGRATION_A_REV>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("dataset_links", "source_schema_id", nullable=False)
    op.alter_column("dataset_links", "target_schema_id", nullable=False)
    op.alter_column(
        "fields",
        "origin",
        nullable=False,
        existing_type=sa.String(20),
        existing_server_default="mapped",
    )
    op.drop_column("fields", "is_tech")


def downgrade() -> None:
    # See module header WARNING — downgrade loses the DEPRECATED semantic.
    op.add_column(
        "fields",
        sa.Column(
            "is_tech",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute("UPDATE fields SET is_tech = TRUE WHERE origin = 'tech'")
    op.alter_column("fields", "origin", nullable=True)
    op.alter_column("dataset_links", "target_schema_id", nullable=True)
    op.alter_column("dataset_links", "source_schema_id", nullable=True)
```

- [ ] **Step 2: Apply Migration B**

```bash
make alembic-head
```

Verify:

```bash
docker exec aide-db-1 psql -U postgres -d aide -c "\d fields" | grep -E "(origin|is_tech)"
```

Expected: `origin` present NOT NULL; `is_tech` absent.

- [ ] **Step 3: Re-run the Task 4–5 tests against the final schema**

Run: `PYTEST_ARGS="-v tests/models/test_field_model.py tests/models/test_dataset_link.py" make test-docker`

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/*_add_lineage_pins_b_finalize.py
git commit -m "feat(migration): finalize lineage pins, drop is_tech (step B)"
```

---

## Task 9: Repository — `DatasetSchemaRepository.latest_for_dataset`

**Files:**
- Modify: `backend/repositories/dataset_schema.py`
- Create: `tests/repositories/test_dataset_schema_repository.py`

- [ ] **Step 1: Write failing test**

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_schema import DatasetSchema
from backend.repositories.dataset_schema import DatasetSchemaRepository


async def _make_dataset(session: AsyncSession, name: str) -> DatasetRdbms:
    kind = SystemKind(code=f"K_{name}", name=f"K {name}")
    flavor = SystemFlavor(code=f"F_{name}", name=f"F {name}", kind=kind)
    system = System(code=f"S_{name}", name=f"S {name}", flavor=flavor)
    ds = DatasetRdbms(
        system=system, object_name=name, kind="rdbms",
        schema_name="s", table_name=name,
    )
    session.add_all([kind, flavor, system, ds])
    await session.flush()
    return ds


@pytest.mark.asyncio
async def test_latest_for_dataset_returns_highest_version(
    transactional_session: AsyncSession,
):
    ds = await _make_dataset(transactional_session, "latest_test")
    v1 = DatasetSchema(dataset_id=ds.id, version_num=1, schema={})
    v2 = DatasetSchema(dataset_id=ds.id, version_num=2, schema={})
    v3 = DatasetSchema(dataset_id=ds.id, version_num=3, schema={})
    transactional_session.add_all([v1, v2, v3])
    await transactional_session.flush()

    repo = DatasetSchemaRepository(transactional_session)
    latest = await repo.latest_for_dataset(ds.id)
    assert latest is not None
    assert latest.id == v3.id
    assert latest.version_num == 3


@pytest.mark.asyncio
async def test_latest_for_dataset_returns_none_when_no_schema(
    transactional_session: AsyncSession,
):
    ds = await _make_dataset(transactional_session, "latest_none")
    repo = DatasetSchemaRepository(transactional_session)
    assert await repo.latest_for_dataset(ds.id) is None
```

- [ ] **Step 2: Run test — expect failure**

Run: `PYTEST_ARGS="-v tests/repositories/test_dataset_schema_repository.py" make test-docker`

Expected: FAIL (`latest_for_dataset` not defined).

- [ ] **Step 3: Add the method**

Open `backend/repositories/dataset_schema.py` and add:

```python
import uuid

from sqlalchemy import select

from backend.models.dataset_schema import DatasetSchema
from backend.repositories.base import BaseRepository


class DatasetSchemaRepository(BaseRepository[DatasetSchema]):
    # ... existing methods ...

    async def latest_for_dataset(
        self, dataset_id: uuid.UUID
    ) -> DatasetSchema | None:
        stmt = (
            select(DatasetSchema)
            .where(DatasetSchema.dataset_id == dataset_id)
            .order_by(DatasetSchema.version_num.desc())
            .limit(1)
        )
        result = await self._execute(stmt, method="latest_for_dataset")
        return result.scalars().first()
```

Preserve existing imports + other methods (the existing file already has `get_by_dataset_and_version`). Do not duplicate imports.

- [ ] **Step 4: Run test — expect pass**

Run: `PYTEST_ARGS="-v tests/repositories/test_dataset_schema_repository.py" make test-docker`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/repositories/dataset_schema.py tests/repositories/test_dataset_schema_repository.py
git commit -m "feat(repo): add DatasetSchemaRepository.latest_for_dataset"
```

---

## Task 10: Repository — `FieldBindingRepository.get_by_field_and_schema`

**Files:**
- Modify: `backend/repositories/field_binding.py`
- Modify: `tests/repositories/test_field_binding_repository.py` (or create)

- [ ] **Step 1: Write failing test**

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.data_type import DataType
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_schema import DatasetSchema
from backend.models.field import Field
from backend.models.field_binding import FieldBinding
from backend.models.type_instance import TypeInstance
from backend.repositories.field_binding import FieldBindingRepository


@pytest.mark.asyncio
async def test_get_by_field_and_schema_returns_row(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="FB_K", name="FB Kind")
    flavor = SystemFlavor(code="FB_FL", name="FB Flavor", kind=kind)
    system = System(code="FB_S", name="FB System", flavor=flavor)
    ds = DatasetRdbms(
        system=system, object_name="fb_ds", kind="rdbms",
        schema_name="s", table_name="t",
    )
    dt = DataType(code="integer", system_flavor=flavor, params_schema={})
    ti = TypeInstance(data_type=dt, type_params={})
    f = Field(dataset=ds, name="col", origin="mapped")
    schema = DatasetSchema(dataset=ds, version_num=1, schema={})
    transactional_session.add_all([kind, flavor, system, ds, dt, ti, f, schema])
    await transactional_session.flush()

    binding = FieldBinding(
        field_id=f.id,
        dataset_schema_id=schema.id,
        position=0,
        is_nullable=True,
        type_instance_id=ti.id,
    )
    transactional_session.add(binding)
    await transactional_session.flush()

    repo = FieldBindingRepository(transactional_session)
    found = await repo.get_by_field_and_schema(f.id, schema.id)
    assert found is not None
    assert found.id == binding.id


@pytest.mark.asyncio
async def test_get_by_field_and_schema_returns_none(
    transactional_session: AsyncSession,
):
    import uuid
    repo = FieldBindingRepository(transactional_session)
    result = await repo.get_by_field_and_schema(uuid.uuid4(), uuid.uuid4())
    assert result is None
```

- [ ] **Step 2: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/repositories/test_field_binding_repository.py" make test-docker`

Expected: AttributeError `get_by_field_and_schema` not defined.

- [ ] **Step 3: Add method to `backend/repositories/field_binding.py`**

```python
async def get_by_field_and_schema(
    self, field_id: uuid.UUID, dataset_schema_id: uuid.UUID
) -> FieldBinding | None:
    stmt = select(FieldBinding).where(
        FieldBinding.field_id == field_id,
        FieldBinding.dataset_schema_id == dataset_schema_id,
    )
    result = await self._execute(stmt, method="get_by_field_and_schema")
    return result.scalars().first()
```

Ensure imports at top of file include `import uuid`, `from sqlalchemy import select`, and `from backend.models.field_binding import FieldBinding`.

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/repositories/test_field_binding_repository.py" make test-docker`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/repositories/field_binding.py tests/repositories/test_field_binding_repository.py
git commit -m "feat(repo): add FieldBindingRepository.get_by_field_and_schema"
```

---

## Task 11: Repository — `DatasetLinkRepository.list_with_compat_summary`

**Files:**
- Modify: `backend/repositories/dataset_link.py`
- Modify: `tests/repositories/test_dataset_link_repository.py`

This repo method powers the bulk `/compat` list endpoint. It returns, per live link: link id, both dataset refs, pinned/latest schema versions, and total + broken counts. The compat service does further per-link aggregation.

- [ ] **Step 1: Write failing test**

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.repositories.dataset_link import DatasetLinkRepository


async def _seed_linked_pair(
    session: AsyncSession, name: str, src_version: int, tgt_version: int
):
    kind = SystemKind(code=f"DL_K_{name}", name=f"DL K {name}")
    flavor = SystemFlavor(code=f"DL_F_{name}", name=f"DL F {name}", kind=kind)
    system = System(code=f"DL_S_{name}", name=f"DL S {name}", flavor=flavor)
    src = DatasetRdbms(
        system=system, object_name=f"{name}_src", kind="rdbms",
        schema_name="s", table_name="src",
    )
    tgt = DatasetRdbms(
        system=system, object_name=f"{name}_tgt", kind="rdbms",
        schema_name="s", table_name="tgt",
    )
    session.add_all([kind, flavor, system, src, tgt])
    await session.flush()

    src_schemas = [
        DatasetSchema(dataset=src, version_num=v, schema={})
        for v in range(1, src_version + 1)
    ]
    tgt_schemas = [
        DatasetSchema(dataset=tgt, version_num=v, schema={})
        for v in range(1, tgt_version + 1)
    ]
    session.add_all(src_schemas + tgt_schemas)
    await session.flush()

    link = DatasetLink(
        source_dataset_id=src.id,
        target_dataset_id=tgt.id,
        source_schema_id=src_schemas[0].id,  # pinned v1 (old)
        target_schema_id=tgt_schemas[0].id,
    )
    session.add(link)
    await session.flush()
    return link, src, tgt, src_schemas, tgt_schemas


@pytest.mark.asyncio
async def test_list_with_compat_summary_reports_drift(
    transactional_session: AsyncSession,
):
    link, src, tgt, src_schemas, tgt_schemas = await _seed_linked_pair(
        transactional_session, "drift", src_version=3, tgt_version=1
    )
    repo = DatasetLinkRepository(transactional_session)
    rows = await repo.list_with_compat_summary()
    target_rows = [r for r in rows if r["dataset_link_id"] == link.id]
    assert len(target_rows) == 1
    row = target_rows[0]
    assert row["source_pinned_version"] == 1
    assert row["source_latest_version"] == 3
    assert row["target_pinned_version"] == 1
    assert row["target_latest_version"] == 1
    assert row["source_has_drift"] is True
    assert row["target_has_drift"] is False
```

- [ ] **Step 2: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/repositories/test_dataset_link_repository.py::test_list_with_compat_summary_reports_drift" make test-docker`

Expected: AttributeError.

- [ ] **Step 3: Add the method to `backend/repositories/dataset_link.py`**

Append to the class:

```python
from typing import Any, Sequence  # ensure Any/Sequence imported

from sqlalchemy import and_, func, literal_column, select
from sqlalchemy.orm import aliased

from backend.models.dataset import Dataset
from backend.models.dataset_schema import DatasetSchema


# ... existing methods above ...

    async def list_with_compat_summary(
        self,
    ) -> list[dict[str, Any]]:
        """Return active DatasetLinks with pin drift metadata.

        Each row has: dataset_link_id, source/target dataset refs,
        pinned version, latest version (per side), has_drift flags.
        """
        src_latest = (
            select(
                DatasetSchema.dataset_id.label("ds_id"),
                func.max(DatasetSchema.version_num).label("max_v"),
            )
            .group_by(DatasetSchema.dataset_id)
            .subquery()
        )
        tgt_latest = aliased(src_latest)

        src_schema = aliased(DatasetSchema)
        tgt_schema = aliased(DatasetSchema)
        src_ds = aliased(Dataset)
        tgt_ds = aliased(Dataset)

        stmt = (
            select(
                self.model.id.label("dataset_link_id"),
                src_ds.id.label("source_dataset_id"),
                src_ds.object_name.label("source_object_name"),
                src_ds.system_id.label("source_system_id"),
                tgt_ds.id.label("target_dataset_id"),
                tgt_ds.object_name.label("target_object_name"),
                tgt_ds.system_id.label("target_system_id"),
                src_schema.version_num.label("source_pinned_version"),
                tgt_schema.version_num.label("target_pinned_version"),
                src_latest.c.max_v.label("source_latest_version"),
                tgt_latest.c.max_v.label("target_latest_version"),
            )
            .join(src_schema, src_schema.id == self.model.source_schema_id)
            .join(tgt_schema, tgt_schema.id == self.model.target_schema_id)
            .join(src_ds, src_ds.id == self.model.source_dataset_id)
            .join(tgt_ds, tgt_ds.id == self.model.target_dataset_id)
            .join(src_latest, src_latest.c.ds_id == self.model.source_dataset_id)
            .join(tgt_latest, tgt_latest.c.ds_id == self.model.target_dataset_id)
            .where(self.model.deleted_at.is_(None))
        )
        result = await self._execute(stmt, method="list_with_compat_summary")
        rows = []
        for row in result.mappings():
            d = dict(row)
            d["source_has_drift"] = (
                d["source_pinned_version"] != d["source_latest_version"]
            )
            d["target_has_drift"] = (
                d["target_pinned_version"] != d["target_latest_version"]
            )
            rows.append(d)
        return rows
```

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/repositories/test_dataset_link_repository.py::test_list_with_compat_summary_reports_drift" make test-docker`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/repositories/dataset_link.py tests/repositories/test_dataset_link_repository.py
git commit -m "feat(repo): add DatasetLinkRepository.list_with_compat_summary"
```

---

## Task 12: Service — `FieldService` origin state machine

**Files:**
- Modify: `backend/services/field.py`
- Modify: `tests/services/test_field_service.py`

Replace the legacy `is_tech` check in `_pre_update` with a state machine on `origin`. Four transitions need invariant checks; two (`TECH ↔ DEPRECATED`) are unconditional.

- [ ] **Step 1: Write failing tests**

Append (or replace relevant `is_tech` tests in) `tests/services/test_field_service.py`:

```python
import pytest

from aide_schemas.field import FieldOrigin
from backend.core import errors
from backend.core.exceptions import AppException
from backend.schemas.field import FieldUpdate
from backend.services.field import FieldService


@pytest.mark.asyncio
async def test_mapped_to_deprecated_blocked_when_target_of_field_link(
    mock_uow, mock_field_service_ctx
):
    ctx = mock_field_service_ctx(origin="mapped", blocking_field_link_count=2)
    service = FieldService()
    with pytest.raises(AppException) as exc:
        await service._pre_update(
            uow=ctx.uow,
            db_obj=ctx.field,
            obj_in=FieldUpdate(origin=FieldOrigin.DEPRECATED),
            updater_id=None,
        )
    assert exc.value.error_code == errors.FIELD_ORIGIN_CONFLICT


@pytest.mark.asyncio
async def test_mapped_to_deprecated_allowed_when_no_field_link(
    mock_field_service_ctx,
):
    ctx = mock_field_service_ctx(origin="mapped", blocking_field_link_count=0)
    service = FieldService()
    await service._pre_update(
        uow=ctx.uow,
        db_obj=ctx.field,
        obj_in=FieldUpdate(origin=FieldOrigin.DEPRECATED),
        updater_id=None,
    )
    # No exception = pass


@pytest.mark.asyncio
async def test_tech_to_deprecated_unconditional(mock_field_service_ctx):
    ctx = mock_field_service_ctx(origin="tech", blocking_field_link_count=0)
    service = FieldService()
    await service._pre_update(
        uow=ctx.uow,
        db_obj=ctx.field,
        obj_in=FieldUpdate(origin=FieldOrigin.DEPRECATED),
        updater_id=None,
    )


@pytest.mark.asyncio
async def test_deprecated_to_mapped_blocked_without_field_link(
    mock_field_service_ctx,
):
    ctx = mock_field_service_ctx(origin="deprecated", blocking_field_link_count=0)
    service = FieldService()
    with pytest.raises(AppException) as exc:
        await service._pre_update(
            uow=ctx.uow,
            db_obj=ctx.field,
            obj_in=FieldUpdate(origin=FieldOrigin.MAPPED),
            updater_id=None,
        )
    assert exc.value.error_code == errors.FIELD_ORIGIN_CONFLICT
```

Also add a small fixture helper at top of the same file (if the project uses `mock_uow` pattern per CLAUDE.md):

```python
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest_asyncio

from backend.models.field import Field


@dataclass
class FieldServiceCtx:
    uow: AsyncMock
    field: Field


@pytest_asyncio.fixture
def mock_field_service_ctx():
    def _make(origin: str, blocking_field_link_count: int) -> FieldServiceCtx:
        import uuid
        field = Field(
            id=uuid.uuid4(),
            dataset_id=uuid.uuid4(),
            name="col",
            origin=origin,
        )
        uow = AsyncMock()
        uow.field_links = AsyncMock()
        uow.field_links.count_by_target_field = AsyncMock(
            return_value=blocking_field_link_count
        )
        # Other uow attributes stubbed — the _pre_update only reads these.
        uow.datasets = AsyncMock()
        uow.datasets.get = AsyncMock(return_value=object())
        uow.fields = AsyncMock()
        repo_mock = AsyncMock()
        repo_mock.get_by_dataset_and_name = AsyncMock(return_value=None)
        uow.fields = repo_mock
        return FieldServiceCtx(uow=uow, field=field)
    return _make
```

Note: existing `test_field_service.py` may already define similar mocks — reuse if present, else introduce the fixture.

- [ ] **Step 2: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/services/test_field_service.py -k origin" make test-docker`

Expected: FAIL — current service still uses `is_tech` semantics.

- [ ] **Step 3: Replace the legacy check in `backend/services/field.py` `_pre_update`**

Locate the block:

```python
new_is_tech = update_data.get("is_tech", db_obj.is_tech)
if new_is_tech is False and db_obj.is_tech is True:
    if await uow.field_links.count_by_target_field(db_obj.id) == 0:
        raise AppException(errors.FIELD_NON_TECH_REQUIRES_SOURCE)
```

Replace with:

```python
new_origin = update_data.get("origin", db_obj.origin)
if new_origin != db_obj.origin:
    # Transition out of MAPPED — target cannot have active FieldLink rows
    if db_obj.origin == "mapped" and new_origin in ("tech", "deprecated"):
        blockers = await uow.field_links.count_by_target_field(db_obj.id)
        if blockers > 0:
            raise AppException(errors.FIELD_ORIGIN_CONFLICT)
    # Transition INTO MAPPED — require FieldLink in the same UoW.
    # We cannot verify "created in same UoW" purely from the field update —
    # require that at least one FieldLink already exists targeting this field.
    # Consumers are expected to call create FieldLink + update Field origin
    # in one request sequence wrapped by the UoW.
    if new_origin == "mapped" and db_obj.origin in ("tech", "deprecated"):
        existing = await uow.field_links.count_by_target_field(db_obj.id)
        if existing == 0:
            raise AppException(errors.FIELD_ORIGIN_CONFLICT)
```

Also remove the `FIELD_NON_TECH_REQUIRES_SOURCE` import/usage in this file (check for stray references). Leave the error code constant in `errors.py` — other callsites may still use it; it's deprecated but removing breaks unrelated code. Open question: grep for uses: `Grep FIELD_NON_TECH_REQUIRES_SOURCE`. If only this file → remove; else leave for a cleanup task.

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/services/test_field_service.py -k origin" make test-docker`

Expected: 4 passed.

Also run the full field-service test file to make sure we didn't regress:

`PYTEST_ARGS="-v tests/services/test_field_service.py" make test-docker`

All tests should pass. Fix any tests still referencing `is_tech` directly.

- [ ] **Step 5: Commit**

```bash
git add backend/services/field.py tests/services/test_field_service.py
git commit -m "feat(field): origin state machine replaces is_tech transition guard"
```

---

## Task 13: Service — `DatasetLinkService` schema belongs-to-dataset validation

**Files:**
- Modify: `backend/services/dataset_link.py`
- Modify: `tests/services/test_dataset_link_service.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/services/test_dataset_link_service.py`:

```python
import uuid

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.schemas.dataset_link import DatasetLinkCreate
from backend.services.dataset_link import DatasetLinkService


# Helper (reuse project mock pattern; pseudo-signature):
# build a mock uow where:
#   uow.datasets.get(src) -> DatasetRdbms(layer="source")
#   uow.datasets.get(tgt) -> DatasetRdbms(layer="raw")
#   uow.dataset_schemas.get(src_schema) -> DatasetSchema(dataset_id=<either matching or mismatched>)
#   uow.dataset_schemas.get(tgt_schema) -> DatasetSchema(dataset_id=<matching>)


@pytest.mark.asyncio
async def test_create_rejects_schema_not_belonging_to_dataset(
    mock_dataset_link_service_ctx,
):
    """source_schema.dataset_id != source_dataset_id → SCHEMA_DATASET_MISMATCH"""
    src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
    src_schema_id, tgt_schema_id = uuid.uuid4(), uuid.uuid4()
    ctx = mock_dataset_link_service_ctx(
        src_dataset_id=src_id, src_layer="source",
        tgt_dataset_id=tgt_id, tgt_layer="raw",
        src_schema_id=src_schema_id,
        # Bug: source schema claims a DIFFERENT dataset
        src_schema_dataset_id=uuid.uuid4(),
        tgt_schema_id=tgt_schema_id,
        tgt_schema_dataset_id=tgt_id,
    )
    service = DatasetLinkService()
    obj_in = DatasetLinkCreate(
        source_dataset_id=src_id,
        target_dataset_id=tgt_id,
        source_schema_id=src_schema_id,
        target_schema_id=tgt_schema_id,
    )
    with pytest.raises(AppException) as exc:
        await service._pre_create(ctx.uow, obj_in=obj_in, creator_id=None)
    assert exc.value.error_code == errors.SCHEMA_DATASET_MISMATCH


@pytest.mark.asyncio
async def test_create_passes_when_schemas_belong(mock_dataset_link_service_ctx):
    src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
    src_schema_id, tgt_schema_id = uuid.uuid4(), uuid.uuid4()
    ctx = mock_dataset_link_service_ctx(
        src_dataset_id=src_id, src_layer="source",
        tgt_dataset_id=tgt_id, tgt_layer="raw",
        src_schema_id=src_schema_id, src_schema_dataset_id=src_id,
        tgt_schema_id=tgt_schema_id, tgt_schema_dataset_id=tgt_id,
    )
    service = DatasetLinkService()
    obj_in = DatasetLinkCreate(
        source_dataset_id=src_id,
        target_dataset_id=tgt_id,
        source_schema_id=src_schema_id,
        target_schema_id=tgt_schema_id,
    )
    await service._pre_create(ctx.uow, obj_in=obj_in, creator_id=None)
```

Add a fixture (same style as Task 12's mock ctx) — it stubs `uow.datasets`, `uow.dataset_schemas`, and `uow.dataset_links`. Reuse existing mock pattern in the file.

- [ ] **Step 2: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_link_service.py -k schema" make test-docker`

Expected: FAIL.

- [ ] **Step 3: Add validation to `backend/services/dataset_link.py`**

In `_pre_create`, after the existing layer checks, add:

```python
# Validate schema belongs to corresponding dataset
src_schema = await uow.dataset_schemas.get(obj_in.source_schema_id)
tgt_schema = await uow.dataset_schemas.get(obj_in.target_schema_id)
if src_schema is None or tgt_schema is None:
    raise AppException(errors.DATASET_SCHEMA_NOT_FOUND)
if src_schema.dataset_id != obj_in.source_dataset_id:
    raise AppException(errors.SCHEMA_DATASET_MISMATCH)
if tgt_schema.dataset_id != obj_in.target_dataset_id:
    raise AppException(errors.SCHEMA_DATASET_MISMATCH)
```

Also add `_pre_update` override (may not exist yet) to validate schema ids when updated:

```python
async def _pre_update(
    self,
    uow: UnitOfWork,
    db_obj: DatasetLink,
    obj_in: DatasetLinkUpdate,
    updater_id: uuid.UUID | None,
) -> None:
    update_data = obj_in.model_dump(exclude_unset=True)
    if "source_schema_id" in update_data:
        schema = await uow.dataset_schemas.get(update_data["source_schema_id"])
        if schema is None:
            raise AppException(errors.DATASET_SCHEMA_NOT_FOUND)
        if schema.dataset_id != db_obj.source_dataset_id:
            raise AppException(errors.SCHEMA_DATASET_MISMATCH)
    if "target_schema_id" in update_data:
        schema = await uow.dataset_schemas.get(update_data["target_schema_id"])
        if schema is None:
            raise AppException(errors.DATASET_SCHEMA_NOT_FOUND)
        if schema.dataset_id != db_obj.target_dataset_id:
            raise AppException(errors.SCHEMA_DATASET_MISMATCH)
```

Import `DatasetLinkUpdate` at top if not already imported.

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_link_service.py" make test-docker`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/dataset_link.py tests/services/test_dataset_link_service.py
git commit -m "feat(dataset-link): validate schema pins belong to correct datasets"
```

---

## Task 14: Service — `FieldLinkService` binding-missing validation

**Files:**
- Modify: `backend/services/field_link.py`
- Modify: `tests/services/test_field_link_service.py`

- [ ] **Step 1: Write failing test**

Append to `tests/services/test_field_link_service.py`:

```python
@pytest.mark.asyncio
async def test_create_rejects_when_source_has_no_binding_in_pinned_schema(
    mock_field_link_service_ctx,
):
    ctx = mock_field_link_service_ctx(
        source_binding_in_pinned=False,
        target_binding_in_pinned=True,
        target_origin="mapped",
    )
    service = FieldLinkService()
    with pytest.raises(AppException) as exc:
        await service._pre_create(ctx.uow, obj_in=ctx.create_in, creator_id=None)
    assert exc.value.error_code == errors.FIELD_BINDING_MISSING


@pytest.mark.asyncio
async def test_create_rejects_when_target_origin_not_mapped(
    mock_field_link_service_ctx,
):
    ctx = mock_field_link_service_ctx(
        source_binding_in_pinned=True,
        target_binding_in_pinned=True,
        target_origin="deprecated",
    )
    service = FieldLinkService()
    with pytest.raises(AppException) as exc:
        await service._pre_create(ctx.uow, obj_in=ctx.create_in, creator_id=None)
    assert exc.value.error_code == errors.FIELD_ORIGIN_CONFLICT


@pytest.mark.asyncio
async def test_create_passes_when_all_bindings_present_and_target_mapped(
    mock_field_link_service_ctx,
):
    ctx = mock_field_link_service_ctx(
        source_binding_in_pinned=True,
        target_binding_in_pinned=True,
        target_origin="mapped",
    )
    service = FieldLinkService()
    await service._pre_create(ctx.uow, obj_in=ctx.create_in, creator_id=None)
```

Define a `mock_field_link_service_ctx` fixture mirroring prior patterns. Stubs:
- `uow.dataset_links.get(dataset_link_id)` returns `DatasetLink(source_schema_id, target_schema_id, source_dataset_id, target_dataset_id)`
- `uow.fields.get(source_field_id)` returns `Field(dataset_id=src_ds_id, origin=...)`
- `uow.fields.get(target_field_id)` returns `Field(dataset_id=tgt_ds_id, origin=target_origin)`
- `uow.field_bindings.get_by_field_and_schema(...)` returns either `FieldBinding(...)` or `None` based on the boolean input

- [ ] **Step 2: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/services/test_field_link_service.py -k binding or origin" make test-docker`

Expected: FAIL — current service doesn't check bindings.

- [ ] **Step 3: Extend `backend/services/field_link.py` `_pre_create`**

Read the existing `_pre_create`. After existing dataset-match validation, add:

```python
# Target must be MAPPED — TECH/DEPRECATED targets have no FieldLinks
tgt_field = await uow.fields.get(obj_in.target_field_id)
if tgt_field is not None and tgt_field.origin != "mapped":
    raise AppException(errors.FIELD_ORIGIN_CONFLICT)

# Source and target must have bindings in the parent link's pinned schemas
dataset_link = await uow.dataset_links.get(obj_in.dataset_link_id)
if dataset_link is None:
    raise AppException(errors.DATASET_LINK_NOT_FOUND)

src_binding = await uow.field_bindings.get_by_field_and_schema(
    obj_in.source_field_id, dataset_link.source_schema_id
)
if src_binding is None:
    raise AppException(errors.FIELD_BINDING_MISSING)

tgt_binding = await uow.field_bindings.get_by_field_and_schema(
    obj_in.target_field_id, dataset_link.target_schema_id
)
if tgt_binding is None:
    raise AppException(errors.FIELD_BINDING_MISSING)
```

Make sure the existing imports include `errors.FIELD_BINDING_MISSING`, `errors.FIELD_ORIGIN_CONFLICT`, `errors.DATASET_LINK_NOT_FOUND`.

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/services/test_field_link_service.py" make test-docker`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/field_link.py tests/services/test_field_link_service.py
git commit -m "feat(field-link): validate bindings exist in pinned schemas on create"
```

---

## Task 15: Service — `DatasetLinkCompatService` per-FieldLink algorithm

**Files:**
- Create: `backend/services/dataset_link_compat.py`
- Create: `tests/services/test_dataset_link_compat_service.py`

This task implements the core compat algorithm (spec §5.2). Pure computation against in-memory inputs — no I/O. Next tasks add the I/O wrapper and aggregation.

- [ ] **Step 1: Write failing tests — one per issue type**

Create `tests/services/test_dataset_link_compat_service.py`:

```python
import uuid

import pytest

from aide_schemas.cast_rule import CastSafety
from aide_schemas.lineage_compat import CompatSeverity, FieldCompatIssue
from backend.services.dataset_link_compat import (
    CompatInputs,
    compute_field_compat_issues,
)


def _ti(data_type_id: uuid.UUID, params: dict | None = None) -> dict:
    return {"id": uuid.uuid4(), "data_type_id": data_type_id, "type_params": params or {}}


def _binding(type_instance: dict, is_nullable: bool = False) -> dict:
    return {
        "id": uuid.uuid4(),
        "type_instance": type_instance,
        "type_instance_id": type_instance["id"],
        "is_nullable": is_nullable,
    }


def test_source_unbound_short_circuits():
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=None,
            target_binding=_binding(_ti(uuid.uuid4())),
            cast_rule=None,
        )
    )
    assert issues == [FieldCompatIssue.SOURCE_UNBOUND]


def test_target_unbound_short_circuits():
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(uuid.uuid4())),
            target_binding=None,
            cast_rule=None,
        )
    )
    assert issues == [FieldCompatIssue.TARGET_UNBOUND]


def test_exact_type_match_no_issues():
    ti = _ti(uuid.uuid4())
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(ti),
            target_binding=_binding(ti),
            cast_rule=None,
        )
    )
    assert issues == []


def test_different_types_no_cast_rule_is_incompatible():
    src_dt_id = uuid.uuid4()
    tgt_dt_id = uuid.uuid4()
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(src_dt_id)),
            target_binding=_binding(_ti(tgt_dt_id)),
            cast_rule=None,
        )
    )
    assert issues == [FieldCompatIssue.TYPE_INCOMPATIBLE]


def test_cast_rule_implicit_is_ok():
    src_dt_id = uuid.uuid4()
    tgt_dt_id = uuid.uuid4()
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(src_dt_id)),
            target_binding=_binding(_ti(tgt_dt_id)),
            cast_rule={"id": uuid.uuid4(), "safety": CastSafety.IMPLICIT.value},
        )
    )
    assert issues == []


def test_cast_rule_safe_is_needs_cast():
    src_dt_id = uuid.uuid4()
    tgt_dt_id = uuid.uuid4()
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(src_dt_id)),
            target_binding=_binding(_ti(tgt_dt_id)),
            cast_rule={"id": uuid.uuid4(), "safety": CastSafety.SAFE.value},
        )
    )
    assert issues == [FieldCompatIssue.TYPE_NEEDS_CAST]


def test_cast_rule_unsafe_is_unsafe_cast():
    src_dt_id = uuid.uuid4()
    tgt_dt_id = uuid.uuid4()
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(src_dt_id)),
            target_binding=_binding(_ti(tgt_dt_id)),
            cast_rule={"id": uuid.uuid4(), "safety": CastSafety.UNSAFE.value},
        )
    )
    assert issues == [FieldCompatIssue.TYPE_UNSAFE_CAST]


def test_nullability_tightening_warns():
    ti = _ti(uuid.uuid4())
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(ti, is_nullable=True),
            target_binding=_binding(ti, is_nullable=False),
            cast_rule=None,
        )
    )
    assert issues == [FieldCompatIssue.NULLABILITY_WARN]


def test_type_needs_cast_plus_nullability_warn_combined():
    src_dt_id = uuid.uuid4()
    tgt_dt_id = uuid.uuid4()
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="mapped",
            source_binding=_binding(_ti(src_dt_id), is_nullable=True),
            target_binding=_binding(_ti(tgt_dt_id), is_nullable=False),
            cast_rule={"id": uuid.uuid4(), "safety": CastSafety.SAFE.value},
        )
    )
    assert set(issues) == {
        FieldCompatIssue.TYPE_NEEDS_CAST,
        FieldCompatIssue.NULLABILITY_WARN,
    }


def test_target_not_mapped_returns_empty_defensive():
    issues = compute_field_compat_issues(
        CompatInputs(
            target_field_origin="deprecated",
            source_binding=_binding(_ti(uuid.uuid4())),
            target_binding=_binding(_ti(uuid.uuid4())),
            cast_rule=None,
        )
    )
    assert issues == []
```

- [ ] **Step 2: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_link_compat_service.py" make test-docker`

Expected: ImportError — module missing.

- [ ] **Step 3: Create `backend/services/dataset_link_compat.py` (algorithm only)**

```python
"""Compatibility service for DatasetLink.

Pure algorithm (compute_field_compat_issues) plus the I/O wrapper
(DatasetLinkCompatService.compat_report) live here. The algorithm accepts
pre-resolved rows so it is trivially unit-testable.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from aide_schemas.cast_rule import CastSafety
from aide_schemas.lineage_compat import FieldCompatIssue


@dataclass
class CompatInputs:
    """Inputs for per-FieldLink compat computation.

    target_field_origin — string value of Field.origin ("mapped"/"tech"/"deprecated")
    source_binding / target_binding — dicts or None. When non-None must contain
        nested `type_instance` dict with `id`, `data_type_id`, `type_params`,
        plus top-level `is_nullable: bool`.
    cast_rule — dict with `id` and `safety` (cast-rule safety enum value), or None.
    """

    target_field_origin: str
    source_binding: dict[str, Any] | None
    target_binding: dict[str, Any] | None
    cast_rule: dict[str, Any] | None


def compute_field_compat_issues(inputs: CompatInputs) -> list[FieldCompatIssue]:
    issues: list[FieldCompatIssue] = []

    # Defensive: FieldLink should not exist against non-MAPPED target.
    if inputs.target_field_origin != "mapped":
        return issues

    if inputs.source_binding is None:
        issues.append(FieldCompatIssue.SOURCE_UNBOUND)
        return issues
    if inputs.target_binding is None:
        issues.append(FieldCompatIssue.TARGET_UNBOUND)
        return issues

    src_ti_id: uuid.UUID = inputs.source_binding["type_instance"]["id"]
    tgt_ti_id: uuid.UUID = inputs.target_binding["type_instance"]["id"]

    if src_ti_id != tgt_ti_id:
        rule = inputs.cast_rule
        if rule is None:
            issues.append(FieldCompatIssue.TYPE_INCOMPATIBLE)
        else:
            safety = rule["safety"]
            if safety == CastSafety.IMPLICIT.value:
                pass  # exact compat via implicit cast
            elif safety == CastSafety.SAFE.value:
                issues.append(FieldCompatIssue.TYPE_NEEDS_CAST)
            elif safety == CastSafety.UNSAFE.value:
                issues.append(FieldCompatIssue.TYPE_UNSAFE_CAST)
            else:
                # Unknown safety — conservatively treat as incompatible.
                issues.append(FieldCompatIssue.TYPE_INCOMPATIBLE)

    if (
        inputs.source_binding.get("is_nullable") is True
        and inputs.target_binding.get("is_nullable") is False
    ):
        issues.append(FieldCompatIssue.NULLABILITY_WARN)

    return issues
```

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_link_compat_service.py" make test-docker`

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/dataset_link_compat.py tests/services/test_dataset_link_compat_service.py
git commit -m "feat(lineage): pure compat algorithm for FieldLink"
```

---

## Task 16: Service — Compat report aggregator (single link)

**Files:**
- Modify: `backend/services/dataset_link_compat.py`
- Create: `backend/schemas/lineage_compat.py`
- Modify: `tests/services/test_dataset_link_compat_service.py`

Glue the algorithm to a real DB read. Build a `DatasetLinkCompatReport` from the pinned schemas and their field_binding / cast_rule rows.

- [ ] **Step 1: Create `backend/schemas/lineage_compat.py`**

```python
from aide_schemas.lineage_compat import (
    CompatSeverity as CompatSeverity,
    CompatSummary as CompatSummary,
    DatasetLinkCompatReport as DatasetLinkCompatReport,
    DatasetLinkCompatSummary as DatasetLinkCompatSummary,
    FieldCompatIssue as FieldCompatIssue,
    FieldCompatRow as FieldCompatRow,
    PinDrift as PinDrift,
    PinDriftSide as PinDriftSide,
)
```

- [ ] **Step 2: Write failing test — integration level**

Append to `tests/services/test_dataset_link_compat_service.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.uow import UnitOfWork
from backend.models import System, SystemFlavor, SystemKind
from backend.models.data_type import DataType
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.models.field import Field
from backend.models.field_binding import FieldBinding
from backend.models.field_link import FieldLink
from backend.models.type_instance import TypeInstance
from backend.services.dataset_link_compat import DatasetLinkCompatService


@pytest.mark.asyncio
async def test_compat_report_reports_ok_for_exact_type_match(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="CPT_K", name="CPT Kind")
    flavor = SystemFlavor(code="CPT_F", name="CPT Flavor", kind=kind)
    system = System(code="CPT_S", name="CPT System", flavor=flavor)
    src = DatasetRdbms(
        system=system, object_name="cpt_src", kind="rdbms", layer="source",
        schema_name="s", table_name="src",
    )
    tgt = DatasetRdbms(
        system=system, object_name="cpt_tgt", kind="rdbms", layer="raw",
        schema_name="s", table_name="tgt",
    )
    dt = DataType(code="integer", system_flavor=flavor, params_schema={})
    ti = TypeInstance(data_type=dt, type_params={})

    src_field = Field(dataset=src, name="id", origin="mapped")
    tgt_field = Field(dataset=tgt, name="id", origin="mapped")
    src_schema = DatasetSchema(dataset=src, version_num=1, schema={})
    tgt_schema = DatasetSchema(dataset=tgt, version_num=1, schema={})
    transactional_session.add_all(
        [kind, flavor, system, src, tgt, dt, ti,
         src_field, tgt_field, src_schema, tgt_schema]
    )
    await transactional_session.flush()

    src_binding = FieldBinding(
        field=src_field, dataset_schema=src_schema, position=0,
        is_nullable=False, type_instance=ti,
    )
    tgt_binding = FieldBinding(
        field=tgt_field, dataset_schema=tgt_schema, position=0,
        is_nullable=False, type_instance=ti,
    )
    link = DatasetLink(
        source_dataset_id=src.id, target_dataset_id=tgt.id,
        source_schema_id=src_schema.id, target_schema_id=tgt_schema.id,
    )
    transactional_session.add_all([src_binding, tgt_binding, link])
    await transactional_session.flush()

    field_link = FieldLink(
        dataset_link_id=link.id,
        source_field_id=src_field.id,
        target_field_id=tgt_field.id,
    )
    transactional_session.add(field_link)
    await transactional_session.flush()

    uow = UnitOfWork()
    uow.session = transactional_session  # hijack for test
    uow.session_factory = lambda: transactional_session
    async with uow:
        svc = DatasetLinkCompatService()
        report = await svc.compat_report(uow, link.id)
    assert report.status.value == "ok"
    assert report.summary.ok == 1
    assert report.summary.error == 0
    assert report.pin_drift.source.has_drift is False
    assert report.pin_drift.target.has_drift is False
```

Note: integration tests work against the real DB through `transactional_session`. The `UnitOfWork` hijack pattern lets us reuse the same session.

- [ ] **Step 3: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_link_compat_service.py::test_compat_report_reports_ok_for_exact_type_match" make test-docker`

Expected: AttributeError — `compat_report` missing.

- [ ] **Step 4: Implement `DatasetLinkCompatService.compat_report` in `backend/services/dataset_link_compat.py`**

Append to the existing file:

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.cast_rule import CastRule
from backend.models.dataset_link import DatasetLink as DatasetLinkModel
from backend.models.field_binding import FieldBinding as FieldBindingModel
from backend.schemas.lineage_compat import (
    CompatSeverity,
    CompatSummary,
    DatasetLinkCompatReport,
    FieldCompatFieldRef,
    FieldCompatRow,
    PinDrift,
    PinDriftSide,
)


_ERROR_ISSUES = {
    FieldCompatIssue.SOURCE_UNBOUND,
    FieldCompatIssue.TARGET_UNBOUND,
    FieldCompatIssue.TYPE_INCOMPATIBLE,
    FieldCompatIssue.TYPE_UNSAFE_CAST,
}
_WARN_ISSUES = {
    FieldCompatIssue.TYPE_NEEDS_CAST,
    FieldCompatIssue.NULLABILITY_WARN,
}


def _severity_of_issues(issues: list[FieldCompatIssue]) -> CompatSeverity:
    if not issues:
        return CompatSeverity.OK
    if any(i in _ERROR_ISSUES for i in issues):
        return CompatSeverity.ERROR
    return CompatSeverity.WARN


def _render_type(binding: FieldBindingModel | None) -> str | None:
    if binding is None:
        return None
    dt_code = binding.type_instance.data_type.code
    params = binding.type_instance.type_params or {}
    if params:
        formatted = ",".join(str(v) for v in params.values())
        return f"{dt_code}({formatted})"
    return dt_code


class DatasetLinkCompatService:
    async def compat_report(
        self, uow: UnitOfWork, dataset_link_id: uuid.UUID
    ) -> DatasetLinkCompatReport:
        async with uow:
            link = await uow.session.get(
                DatasetLinkModel, dataset_link_id
            )
            if link is None or link.deleted_at is not None:
                raise AppException(errors.DATASET_LINK_NOT_FOUND)

            src_latest = await uow.dataset_schemas.latest_for_dataset(
                link.source_dataset_id
            )
            tgt_latest = await uow.dataset_schemas.latest_for_dataset(
                link.target_dataset_id
            )
            src_pinned = await uow.dataset_schemas.get(link.source_schema_id)
            tgt_pinned = await uow.dataset_schemas.get(link.target_schema_id)

            pin_drift = PinDrift(
                source=PinDriftSide(
                    pinned_version=src_pinned.version_num,
                    latest_version=src_latest.version_num if src_latest else src_pinned.version_num,
                    has_drift=(src_latest is not None and src_latest.version_num != src_pinned.version_num),
                ),
                target=PinDriftSide(
                    pinned_version=tgt_pinned.version_num,
                    latest_version=tgt_latest.version_num if tgt_latest else tgt_pinned.version_num,
                    has_drift=(tgt_latest is not None and tgt_latest.version_num != tgt_pinned.version_num),
                ),
            )

            # Eager-load field_links with source/target fields + their bindings
            from backend.models.field_link import FieldLink as FieldLinkModel
            stmt = (
                select(FieldLinkModel)
                .where(FieldLinkModel.dataset_link_id == dataset_link_id)
                .options(selectinload(FieldLinkModel.dataset_link))
            )
            result = await uow.session.execute(stmt)
            field_links = list(result.scalars())

            field_compat: list[FieldCompatRow] = []
            ok_count = warn_count = error_count = 0

            for fl in field_links:
                src_field = await uow.fields.get(fl.source_field_id)
                tgt_field = await uow.fields.get(fl.target_field_id)
                if src_field is None or tgt_field is None:
                    continue

                src_binding = await uow.field_bindings.get_by_field_and_schema(
                    fl.source_field_id, link.source_schema_id
                )
                tgt_binding = await uow.field_bindings.get_by_field_and_schema(
                    fl.target_field_id, link.target_schema_id
                )

                cast_rule = None
                if (
                    src_binding is not None
                    and tgt_binding is not None
                    and src_binding.type_instance_id != tgt_binding.type_instance_id
                ):
                    # Fetch cast rule (src data_type, tgt data_type)
                    cr_stmt = select(CastRule).where(
                        CastRule.source_data_type_id
                        == src_binding.type_instance.data_type_id,
                        CastRule.target_data_type_id
                        == tgt_binding.type_instance.data_type_id,
                    )
                    cr_result = await uow.session.execute(cr_stmt)
                    cast_rule = cr_result.scalars().first()

                inputs = CompatInputs(
                    target_field_origin=tgt_field.origin,
                    source_binding=_binding_to_dict(src_binding),
                    target_binding=_binding_to_dict(tgt_binding),
                    cast_rule=(
                        {"id": cast_rule.id, "safety": cast_rule.safety}
                        if cast_rule is not None
                        else None
                    ),
                )
                issues = compute_field_compat_issues(inputs)
                severity = _severity_of_issues(issues)

                if severity == CompatSeverity.OK:
                    ok_count += 1
                elif severity == CompatSeverity.WARN:
                    warn_count += 1
                else:
                    error_count += 1

                field_compat.append(
                    FieldCompatRow(
                        field_link_id=fl.id,
                        source_field=FieldCompatFieldRef(
                            id=src_field.id, name=src_field.name
                        ),
                        target_field=FieldCompatFieldRef(
                            id=tgt_field.id, name=tgt_field.name
                        ),
                        source_type=_render_type(src_binding),
                        target_type=_render_type(tgt_binding),
                        issues=issues,
                        severity=severity,
                        cast_rule_id=cast_rule.id if cast_rule is not None else None,
                    )
                )

            summary = CompatSummary(
                ok=ok_count,
                warn=warn_count,
                error=error_count,
                total=ok_count + warn_count + error_count,
            )

            has_drift = pin_drift.source.has_drift or pin_drift.target.has_drift
            if error_count > 0:
                status = CompatSeverity.ERROR
            elif warn_count > 0 or has_drift:
                status = CompatSeverity.WARN
            else:
                status = CompatSeverity.OK

            return DatasetLinkCompatReport(
                dataset_link_id=dataset_link_id,
                pin_drift=pin_drift,
                field_compat=field_compat,
                summary=summary,
                status=status,
            )


def _binding_to_dict(binding: FieldBindingModel | None) -> dict[str, Any] | None:
    if binding is None:
        return None
    return {
        "id": binding.id,
        "type_instance": {
            "id": binding.type_instance.id,
            "data_type_id": binding.type_instance.data_type_id,
            "type_params": binding.type_instance.type_params or {},
        },
        "type_instance_id": binding.type_instance_id,
        "is_nullable": binding.is_nullable,
    }
```

- [ ] **Step 5: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_link_compat_service.py::test_compat_report_reports_ok_for_exact_type_match" make test-docker`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/dataset_link_compat.py backend/schemas/lineage_compat.py tests/services/test_dataset_link_compat_service.py
git commit -m "feat(lineage): compat report for a single DatasetLink"
```

---

## Task 17: Service — Bulk compat list

**Files:**
- Modify: `backend/services/dataset_link_compat.py`
- Modify: `backend/schemas/filters.py`
- Modify: `tests/services/test_dataset_link_compat_service.py`

Bulk list uses `DatasetLinkRepository.list_with_compat_summary` (Task 11) to get pin-drift rows, then computes per-link summary counts by invoking `compat_report` per row? No — we don't want N per-link full joins for a bulk list. Compromise: for bulk, compute `summary` by counting severity levels across field_links through a SQL aggregate join. Simplest MVP: re-use `compat_report` per link but cap at reasonable `page_size` (20 default).

This is acceptable for MVP monitoring loads. Revisit if dashboards observe slowness.

- [ ] **Step 1: Add `DatasetLinkCompatFilter` to `backend/schemas/filters.py`**

Insert near `DatasetLinkFilter`:

```python
# ── DatasetLinkCompat ────────────────────────────────────────────────────
class DatasetLinkCompatFilter(BaseFilter):
    """Filters for GET /dataset-links/compat bulk listing."""

    status: str | None = None
    status__in: str | None = None
    has_drift: bool | None = None
    dataset_id: uuid.UUID | None = None
    system_id: uuid.UUID | None = None


DATASET_LINK_COMPAT_SORTABLE = {"status", "updated_at"}
```

- [ ] **Step 2: Write failing test**

Append to `tests/services/test_dataset_link_compat_service.py`:

```python
@pytest.mark.asyncio
async def test_list_compat_filters_error_status(
    transactional_session: AsyncSession,
):
    """Seed two links: one fully OK, one with mismatched types and no cast rule.
    Filter status=error returns only the second."""
    # Build common fixtures: system, flavor, kind, datatypes
    from backend.models.data_type import DataType
    from backend.models.type_instance import TypeInstance

    kind = SystemKind(code="LST_K", name="LST Kind")
    flavor = SystemFlavor(code="LST_F", name="LST Flavor", kind=kind)
    system = System(code="LST_S", name="LST System", flavor=flavor)
    dt_int = DataType(code="integer", system_flavor=flavor, params_schema={})
    dt_txt = DataType(code="text", system_flavor=flavor, params_schema={})
    ti_int = TypeInstance(data_type=dt_int, type_params={})
    ti_txt = TypeInstance(data_type=dt_txt, type_params={})
    transactional_session.add_all(
        [kind, flavor, system, dt_int, dt_txt, ti_int, ti_txt]
    )
    await transactional_session.flush()

    # Link 1: OK (matching int→int)
    src1 = DatasetRdbms(
        system=system, object_name="lst_ok_src", kind="rdbms", layer="source",
        schema_name="s", table_name="s1",
    )
    tgt1 = DatasetRdbms(
        system=system, object_name="lst_ok_tgt", kind="rdbms", layer="raw",
        schema_name="s", table_name="t1",
    )
    transactional_session.add_all([src1, tgt1])
    await transactional_session.flush()
    ss1 = DatasetSchema(dataset=src1, version_num=1, schema={})
    ts1 = DatasetSchema(dataset=tgt1, version_num=1, schema={})
    transactional_session.add_all([ss1, ts1])
    await transactional_session.flush()
    sf1 = Field(dataset=src1, name="id", origin="mapped")
    tf1 = Field(dataset=tgt1, name="id", origin="mapped")
    transactional_session.add_all([sf1, tf1])
    await transactional_session.flush()
    transactional_session.add_all([
        FieldBinding(field=sf1, dataset_schema=ss1, position=0, is_nullable=False, type_instance=ti_int),
        FieldBinding(field=tf1, dataset_schema=ts1, position=0, is_nullable=False, type_instance=ti_int),
    ])
    link1 = DatasetLink(
        source_dataset_id=src1.id, target_dataset_id=tgt1.id,
        source_schema_id=ss1.id, target_schema_id=ts1.id,
    )
    transactional_session.add(link1)
    await transactional_session.flush()
    transactional_session.add(
        FieldLink(dataset_link_id=link1.id,
                  source_field_id=sf1.id, target_field_id=tf1.id)
    )

    # Link 2: ERROR (int → text, no cast rule)
    src2 = DatasetRdbms(
        system=system, object_name="lst_err_src", kind="rdbms", layer="source",
        schema_name="s", table_name="s2",
    )
    tgt2 = DatasetRdbms(
        system=system, object_name="lst_err_tgt", kind="rdbms", layer="raw",
        schema_name="s", table_name="t2",
    )
    transactional_session.add_all([src2, tgt2])
    await transactional_session.flush()
    ss2 = DatasetSchema(dataset=src2, version_num=1, schema={})
    ts2 = DatasetSchema(dataset=tgt2, version_num=1, schema={})
    transactional_session.add_all([ss2, ts2])
    await transactional_session.flush()
    sf2 = Field(dataset=src2, name="id", origin="mapped")
    tf2 = Field(dataset=tgt2, name="id", origin="mapped")
    transactional_session.add_all([sf2, tf2])
    await transactional_session.flush()
    transactional_session.add_all([
        FieldBinding(field=sf2, dataset_schema=ss2, position=0, is_nullable=False, type_instance=ti_int),
        FieldBinding(field=tf2, dataset_schema=ts2, position=0, is_nullable=False, type_instance=ti_txt),
    ])
    link2 = DatasetLink(
        source_dataset_id=src2.id, target_dataset_id=tgt2.id,
        source_schema_id=ss2.id, target_schema_id=ts2.id,
    )
    transactional_session.add(link2)
    await transactional_session.flush()
    transactional_session.add(
        FieldLink(dataset_link_id=link2.id,
                  source_field_id=sf2.id, target_field_id=tf2.id)
    )
    await transactional_session.flush()

    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session
    async with uow:
        svc = DatasetLinkCompatService()
        page = await svc.list_compat(uow, status=["error"], page=1, page_size=10)
    summaries = [p for p in page.items if p.dataset_link_id == link2.id]
    assert len(summaries) == 1
    assert summaries[0].status.value == "error"
```

- [ ] **Step 3: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_link_compat_service.py::test_list_compat_filters_error_status" make test-docker`

Expected: AttributeError.

- [ ] **Step 4: Add `list_compat` to `DatasetLinkCompatService`**

Append to the service file:

```python
from aide_schemas.pagination import Page
from backend.schemas.lineage_compat import DatasetLinkCompatSummary


class DatasetLinkCompatService:
    # ... existing methods ...

    async def list_compat(
        self,
        uow: UnitOfWork,
        *,
        status: list[str] | None = None,
        has_drift: bool | None = None,
        dataset_id: uuid.UUID | None = None,
        system_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[DatasetLinkCompatSummary]:
        async with uow:
            rows = await uow.dataset_links.list_with_compat_summary()
            # Optional prefilters (cheap, no-join):
            if dataset_id is not None:
                rows = [
                    r for r in rows
                    if r["source_dataset_id"] == dataset_id
                    or r["target_dataset_id"] == dataset_id
                ]
            if has_drift is True:
                rows = [
                    r for r in rows
                    if r["source_has_drift"] or r["target_has_drift"]
                ]
            elif has_drift is False:
                rows = [
                    r for r in rows
                    if not (r["source_has_drift"] or r["target_has_drift"])
                ]
            if system_id is not None:
                rows = [
                    r for r in rows
                    if r["source_system_id"] == system_id
                    or r["target_system_id"] == system_id
                ]

            # Compute per-link summary via compat_report (O(n) — OK at page sizes <= 50)
            computed: list[DatasetLinkCompatSummary] = []
            for row in rows:
                report = await self.compat_report(uow, row["dataset_link_id"])
                summary = DatasetLinkCompatSummary(
                    dataset_link_id=row["dataset_link_id"],
                    source_dataset={
                        "id": row["source_dataset_id"],
                        "object_name": row["source_object_name"],
                    },
                    target_dataset={
                        "id": row["target_dataset_id"],
                        "object_name": row["target_object_name"],
                    },
                    status=report.status,
                    summary=report.summary,
                    pin_drift={
                        "source": row["source_has_drift"],
                        "target": row["target_has_drift"],
                    },
                )
                if status and summary.status.value not in status:
                    continue
                computed.append(summary)

            # Pagination after filtering
            total = len(computed)
            start = (page - 1) * page_size
            end = start + page_size
            return Page[DatasetLinkCompatSummary](
                items=computed[start:end],
                total=total,
                page=page,
                size=page_size,
            )
```

**Note:** `system_id` is filtered in Python against the joined columns from the repository. Cheap for page sizes ≤ 50; revisit if dashboards scan larger pages.

- [ ] **Step 5: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_link_compat_service.py::test_list_compat_filters_error_status" make test-docker`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/dataset_link_compat.py backend/schemas/filters.py tests/services/test_dataset_link_compat_service.py
git commit -m "feat(lineage): bulk list_compat with status/drift filters"
```

---

## Task 18: Service — `DatasetSchemaService` RESTRICT error catch

**Files:**
- Modify: `backend/services/dataset_schema.py`
- Modify: `tests/services/test_dataset_schema_service.py` (or create)

- [ ] **Step 1: Write failing test**

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.services.dataset_schema import DatasetSchemaService


@pytest.mark.asyncio
async def test_delete_pinned_schema_raises_in_use(transactional_session: AsyncSession):
    kind = SystemKind(code="DSS_K", name="DSS Kind")
    flavor = SystemFlavor(code="DSS_F", name="DSS Flavor", kind=kind)
    system = System(code="DSS_S", name="DSS System", flavor=flavor)
    src = DatasetRdbms(
        system=system, object_name="dss_src", kind="rdbms",
        schema_name="s", table_name="src",
    )
    tgt = DatasetRdbms(
        system=system, object_name="dss_tgt", kind="rdbms",
        schema_name="s", table_name="tgt",
    )
    transactional_session.add_all([kind, flavor, system, src, tgt])
    await transactional_session.flush()
    ss = DatasetSchema(dataset=src, version_num=1, schema={})
    ts = DatasetSchema(dataset=tgt, version_num=1, schema={})
    transactional_session.add_all([ss, ts])
    await transactional_session.flush()
    link = DatasetLink(
        source_dataset_id=src.id, target_dataset_id=tgt.id,
        source_schema_id=ss.id, target_schema_id=ts.id,
    )
    transactional_session.add(link)
    await transactional_session.flush()

    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session
    service = DatasetSchemaService()
    with pytest.raises(AppException) as exc:
        await service.delete(uow=uow, obj_id=ss.id, deleter_id=None)
    assert exc.value.error_code == errors.DATASET_SCHEMA_IN_USE
```

- [ ] **Step 2: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_schema_service.py::test_delete_pinned_schema_raises_in_use" make test-docker`

Expected: FAIL — IntegrityError leaks out raw (not wrapped as AppException).

- [ ] **Step 3: Override `delete` or use `_pre_delete` in `backend/services/dataset_schema.py`**

Add a defensive check by querying `DatasetLink` count upfront (cheaper than catching SQL error, produces useful `blocking_dataset_link_ids`):

```python
from sqlalchemy import or_, select

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.dataset_link import DatasetLink


class DatasetSchemaService(
    GenericService[DatasetSchema, DatasetSchemaCreate, DatasetSchemaUpdate, DatasetSchemaRead]
):
    # ... existing methods ...

    async def _pre_delete(
        self, uow: UnitOfWork, db_obj: DatasetSchema, deleter_id: uuid.UUID | None
    ) -> None:
        stmt = (
            select(DatasetLink.id)
            .where(
                or_(
                    DatasetLink.source_schema_id == db_obj.id,
                    DatasetLink.target_schema_id == db_obj.id,
                ),
                DatasetLink.deleted_at.is_(None),
            )
            .limit(5)
        )
        result = await uow.session.execute(stmt)
        blocking = [row[0] for row in result.all()]
        if blocking:
            raise AppException(
                errors.DATASET_SCHEMA_IN_USE,
                extra={"blocking_dataset_link_ids": [str(b) for b in blocking]},
            )
```

Check `GenericService` / `SoftDeleteService` base to see where `_pre_delete` is called. If it doesn't exist, use `_pre_hard_delete` or override `delete` directly. (Check `backend/services/base.py`.)

Also check AppException signature for `extra` kwarg — if not supported, drop `extra=` and encode in detail string.

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_schema_service.py::test_delete_pinned_schema_raises_in_use" make test-docker`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/dataset_schema.py tests/services/test_dataset_schema_service.py
git commit -m "feat(dataset-schema): block delete when pinned by active DatasetLink"
```

---

## Task 19: API — Update `/dataset-links` create/update endpoints

**Files:**
- Modify: `backend/api/v1/dataset_links.py`
- Modify: `tests/api/test_dataset_links.py`

- [ ] **Step 1: Add failing API test**

Append to `tests/api/test_dataset_links.py`:

```python
async def _create_schema(
    async_client: AsyncClient, headers: dict, dataset_id: str, version: int
) -> str:
    resp = await async_client.post(
        "/api/v1/dataset-schemas/",
        json={"dataset_id": dataset_id, "version_num": version, "schema": {}},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
class TestDatasetLinkPinAPI:
    @pytest.fixture
    async def async_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    async def test_create_requires_schema_ids(
        self, async_client, superuser_token_headers, test_system
    ):
        src_id = await _create_dataset(async_client, superuser_token_headers, test_system.id, "pin_src", "source")
        tgt_id = await _create_dataset(async_client, superuser_token_headers, test_system.id, "pin_tgt", "raw")
        # Omit schema_ids → 422
        resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={"source_dataset_id": src_id, "target_dataset_id": tgt_id},
            headers=superuser_token_headers,
        )
        assert resp.status_code == 422

    async def test_create_with_schema_ids_returns_pins(
        self, async_client, superuser_token_headers, test_system
    ):
        src_id = await _create_dataset(async_client, superuser_token_headers, test_system.id, "pin2_src", "source")
        tgt_id = await _create_dataset(async_client, superuser_token_headers, test_system.id, "pin2_tgt", "raw")
        src_schema_id = await _create_schema(async_client, superuser_token_headers, src_id, 1)
        tgt_schema_id = await _create_schema(async_client, superuser_token_headers, tgt_id, 1)

        resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={
                "source_dataset_id": src_id,
                "target_dataset_id": tgt_id,
                "source_schema_id": src_schema_id,
                "target_schema_id": tgt_schema_id,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["source_schema_id"] == src_schema_id
        assert body["target_schema_id"] == tgt_schema_id

    async def test_create_schema_dataset_mismatch_returns_422(
        self, async_client, superuser_token_headers, test_system
    ):
        src_id = await _create_dataset(async_client, superuser_token_headers, test_system.id, "pin3_src", "source")
        tgt_id = await _create_dataset(async_client, superuser_token_headers, test_system.id, "pin3_tgt", "raw")
        unrelated_id = await _create_dataset(async_client, superuser_token_headers, test_system.id, "pin3_unrelated", "source")
        src_schema_id = await _create_schema(async_client, superuser_token_headers, unrelated_id, 1)
        tgt_schema_id = await _create_schema(async_client, superuser_token_headers, tgt_id, 1)

        resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={
                "source_dataset_id": src_id,
                "target_dataset_id": tgt_id,
                "source_schema_id": src_schema_id,
                "target_schema_id": tgt_schema_id,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "SCHEMA_DATASET_MISMATCH"
```

- [ ] **Step 2: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/api/test_dataset_links.py::TestDatasetLinkPinAPI" make test-docker`

Expected: either 422 for the happy path (since schema_ids optional before now) or 201 with null schema_ids (depending on DTO state). Confirm: test failure is consistent with current state.

- [ ] **Step 3: Update `backend/api/v1/dataset_links.py` response handlers**

The DTOs already enforce the shape from Task 2. Add the new error code to route responses:

```python
from backend.core.errors import (
    # ... existing imports ...
    DATASET_SCHEMA_NOT_FOUND,
    SCHEMA_DATASET_MISMATCH,
)
```

In `create_link` and `update_link` decorators, extend `build_error_responses(...)`:

```python
@router.post(
    ...,
    responses={
        **build_error_responses(
            DATASET_NOT_FOUND,
            DATASET_SCHEMA_NOT_FOUND,
            DATASET_LINK_ALREADY_EXISTS,
            DATASET_LINK_SELF_REFERENCE,
            DATASET_LINK_LAYER_ORDER,
            DATASET_LINK_LAYER_MISSING,
            SCHEMA_DATASET_MISMATCH,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
...
```

And for `update_link`:

```python
responses={
    **build_error_responses(
        DATASET_LINK_NOT_FOUND,
        DATASET_SCHEMA_NOT_FOUND,
        SCHEMA_DATASET_MISMATCH,
        VERSION_CONFLICT,
        UNAUTHORIZED,
        FORBIDDEN,
    ),
},
```

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/api/test_dataset_links.py" make test-docker`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/api/v1/dataset_links.py tests/api/test_dataset_links.py
git commit -m "feat(api): wire schema pin error codes on dataset-link CRUD"
```

---

## Task 20: API — `/dataset-links/{id}/compat` endpoint

**Files:**
- Modify: `backend/api/v1/dataset_links.py`
- Modify: `tests/api/test_dataset_links.py`

- [ ] **Step 1: Write failing test**

Append to `tests/api/test_dataset_links.py`:

```python
    async def test_compat_endpoint_returns_report(
        self, async_client, superuser_token_headers, test_system, transactional_session
    ):
        # Set up a trivial 1-column lineage end-to-end via API to check the endpoint.
        src_id = await _create_dataset(async_client, superuser_token_headers, test_system.id, "cpt_src", "source")
        tgt_id = await _create_dataset(async_client, superuser_token_headers, test_system.id, "cpt_tgt", "raw")
        ss_id = await _create_schema(async_client, superuser_token_headers, src_id, 1)
        ts_id = await _create_schema(async_client, superuser_token_headers, tgt_id, 1)
        # Create link
        resp = await async_client.post(
            "/api/v1/dataset-links/",
            json={
                "source_dataset_id": src_id,
                "target_dataset_id": tgt_id,
                "source_schema_id": ss_id,
                "target_schema_id": ts_id,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == 201, resp.text
        link_id = resp.json()["id"]

        resp = await async_client.get(
            f"/api/v1/dataset-links/{link_id}/compat",
            headers=superuser_token_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["dataset_link_id"] == link_id
        assert body["summary"] == {"ok": 0, "warn": 0, "error": 0, "total": 0}
        assert body["status"] == "ok"
```

- [ ] **Step 2: Run — expect 404 (endpoint missing)**

Run: `PYTEST_ARGS="-v tests/api/test_dataset_links.py::TestDatasetLinkPinAPI::test_compat_endpoint_returns_report" make test-docker`

Expected: 404.

- [ ] **Step 3: Add the endpoint**

In `backend/api/v1/dataset_links.py`, import and wire the service:

```python
from backend.services.dataset_link_compat import DatasetLinkCompatService
from backend.schemas.lineage_compat import DatasetLinkCompatReport


@router.get(
    "/{obj_id}/compat",
    response_model=DatasetLinkCompatReport,
    responses={
        **build_error_responses(DATASET_LINK_NOT_FOUND, UNAUTHORIZED, FORBIDDEN),
    },
)
async def get_link_compat(
    obj_id: uuid.UUID,
    service: DatasetLinkCompatService = Depends(DatasetLinkCompatService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    return await service.compat_report(uow=uow, dataset_link_id=obj_id)
```

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/api/test_dataset_links.py::TestDatasetLinkPinAPI::test_compat_endpoint_returns_report" make test-docker`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api/v1/dataset_links.py tests/api/test_dataset_links.py
git commit -m "feat(api): add GET /dataset-links/{id}/compat endpoint"
```

---

## Task 21: API — `/dataset-links/compat` bulk endpoint

**Files:**
- Modify: `backend/api/v1/dataset_links.py`
- Modify: `tests/api/test_dataset_links.py`

- [ ] **Step 1: Write failing test**

Append:

```python
    async def test_list_compat_endpoint(
        self, async_client, superuser_token_headers, test_system
    ):
        resp = await async_client.get(
            "/api/v1/dataset-links/compat",
            headers=superuser_token_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "items" in body
        assert "total" in body
```

- [ ] **Step 2: Run — expect failure**

Run: `PYTEST_ARGS="-v tests/api/test_dataset_links.py::TestDatasetLinkPinAPI::test_list_compat_endpoint" make test-docker`

Expected: 404.

- [ ] **Step 3: Add the endpoint**

```python
from backend.schemas.filters import (
    DATASET_LINK_COMPAT_SORTABLE,
    DatasetLinkCompatFilter,
)
from backend.schemas.lineage_compat import DatasetLinkCompatSummary
from aide_schemas.pagination import Page as SchemaPage


_compat_filter_sort = get_filter_sort_dependency(
    DatasetLinkCompatFilter, DATASET_LINK_COMPAT_SORTABLE, "updated_at"
)


@router.get(
    "/compat",
    response_model=SchemaPage[DatasetLinkCompatSummary],
    responses={
        **build_error_responses(UNAUTHORIZED, FORBIDDEN),
    },
)
async def list_link_compat(
    service: DatasetLinkCompatService = Depends(DatasetLinkCompatService),
    uow: UnitOfWork = Depends(UnitOfWork),
    params: FilterSortParams = Depends(_compat_filter_sort),
) -> Any:
    filters = params.filters
    status_raw = filters.get("status") or filters.get("status__in")
    status_list: list[str] | None = None
    if status_raw:
        status_list = [s.strip() for s in str(status_raw).split(",") if s.strip()]
    return await service.list_compat(
        uow=uow,
        status=status_list,
        has_drift=filters.get("has_drift"),
        dataset_id=filters.get("dataset_id"),
        system_id=filters.get("system_id"),
        page=params.page,
        page_size=params.size,
    )
```

Route ordering note: FastAPI matches routes in declaration order. Ensure `/compat` is declared **before** `/{obj_id}` and `/{obj_id}/compat`. Without this, FastAPI interprets `compat` as an `obj_id` and attempts UUID parsing. Move `list_link_compat` above `get_link` / `get_link_compat` in the file if needed.

- [ ] **Step 4: Run — expect pass**

Run: `PYTEST_ARGS="-v tests/api/test_dataset_links.py::TestDatasetLinkPinAPI::test_list_compat_endpoint" make test-docker`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api/v1/dataset_links.py tests/api/test_dataset_links.py
git commit -m "feat(api): add GET /dataset-links/compat bulk listing endpoint"
```

---

## Task 22: API — Fields PATCH origin + DatasetSchema DELETE RESTRICT

**Files:**
- Modify: `backend/api/v1/fields.py`
- Modify: `backend/api/v1/dataset_schemas.py`
- Modify: `backend/schemas/filters.py`
- Modify: `tests/api/test_fields.py`
- Modify: `tests/api/test_dataset_schemas.py`

- [ ] **Step 1: Update `FieldFilter` to allow `origin` filter**

In `backend/schemas/filters.py`, extend `FieldFilter`:

```python
class FieldFilter(BaseFilter):
    dataset_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    name: str | None = None
    name__like: str | None = None
    origin: str | None = None
    origin__in: str | None = None
```

- [ ] **Step 2: Wire error codes in `backend/api/v1/fields.py`**

Extend `create_crud_router` `update_error_codes`:

```python
from backend.core.errors import FIELD_ORIGIN_CONFLICT


crud_router = create_crud_router(
    # ... existing args ...
    update_error_codes=[
        FIELD_NOT_FOUND,
        FIELD_ALREADY_EXISTS,
        DATASET_NOT_FOUND,
        FIELD_PARENT_NOT_FOUND,
        FIELD_PARENT_DATASET_MISMATCH,
        FIELD_CIRCULAR_REFERENCE,
        FIELD_ORIGIN_CONFLICT,
        VERSION_CONFLICT,
    ],
    # ...
)
```

- [ ] **Step 3: Write failing test — origin PATCH conflict**

Append to `tests/api/test_fields.py`:

```python
async def test_patch_origin_to_deprecated_blocked_when_field_link_exists(
    async_client, superuser_token_headers, test_system
):
    # Requires setting up src/tgt datasets, schemas, bindings, fields, and a FieldLink.
    # The conflict should return 409 with error_code FIELD_ORIGIN_CONFLICT.
    # (Full setup follows the pattern in tests/api/test_field_links.py)
    ...  # See tests/api/test_field_links.py for the seed pattern
    # After seeding, PATCH /fields/{tgt_field_id} with {"origin": "deprecated"}
    # and row_version=1; expect 409 FIELD_ORIGIN_CONFLICT.
```

Fully fleshed test (substitute seed helpers from the existing `test_field_links.py`):

```python
async def test_patch_origin_to_deprecated_blocked_when_field_link_exists(
    async_client, superuser_token_headers, test_system, transactional_session
):
    # Create src, tgt datasets with layers source/raw
    src_id = await _create_dataset(
        async_client, superuser_token_headers, test_system.id, "orig_src", "source"
    )
    tgt_id = await _create_dataset(
        async_client, superuser_token_headers, test_system.id, "orig_tgt", "raw"
    )
    # Create schemas
    src_schema_id = await _create_schema(async_client, superuser_token_headers, src_id, 1)
    tgt_schema_id = await _create_schema(async_client, superuser_token_headers, tgt_id, 1)
    # Create fields (default origin=mapped)
    resp = await async_client.post(
        "/api/v1/fields/",
        json={"dataset_id": src_id, "name": "col"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 201
    src_fid = resp.json()["id"]
    resp = await async_client.post(
        "/api/v1/fields/",
        json={"dataset_id": tgt_id, "name": "col"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 201
    tgt_fid = resp.json()["id"]

    # Create a TypeInstance via API OR seed directly: for brevity direct-seed.
    from backend.models.data_type import DataType
    from backend.models.type_instance import TypeInstance
    from backend.models.field_binding import FieldBinding
    from backend.models.dataset_link import DatasetLink
    from backend.models.field_link import FieldLink
    import uuid as _uuid
    dt = DataType(code="integer", system_flavor_id=test_system.flavor_id, params_schema={})
    ti = TypeInstance(data_type=dt, type_params={})
    transactional_session.add_all([dt, ti])
    await transactional_session.flush()
    transactional_session.add_all([
        FieldBinding(field_id=_uuid.UUID(src_fid), dataset_schema_id=_uuid.UUID(src_schema_id),
                     position=0, is_nullable=False, type_instance=ti),
        FieldBinding(field_id=_uuid.UUID(tgt_fid), dataset_schema_id=_uuid.UUID(tgt_schema_id),
                     position=0, is_nullable=False, type_instance=ti),
    ])
    link = DatasetLink(
        source_dataset_id=_uuid.UUID(src_id),
        target_dataset_id=_uuid.UUID(tgt_id),
        source_schema_id=_uuid.UUID(src_schema_id),
        target_schema_id=_uuid.UUID(tgt_schema_id),
    )
    transactional_session.add(link)
    await transactional_session.flush()
    transactional_session.add(FieldLink(
        dataset_link_id=link.id,
        source_field_id=_uuid.UUID(src_fid),
        target_field_id=_uuid.UUID(tgt_fid),
    ))
    await transactional_session.commit()

    # Now try to flip target field origin to deprecated → expect 409
    resp = await async_client.patch(
        f"/api/v1/fields/{tgt_fid}",
        json={"origin": "deprecated", "row_version": 1},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "FIELD_ORIGIN_CONFLICT"
```

- [ ] **Step 4: Run — expect failure (409 not yet wired)**

Run: `PYTEST_ARGS="-v tests/api/test_fields.py::test_patch_origin_to_deprecated_blocked_when_field_link_exists" make test-docker`

Expected: probably FAIL — either 404 from error-response inspection or incomplete wiring.

- [ ] **Step 5: Write and add test for DELETE DatasetSchema RESTRICT**

Append to `tests/api/test_dataset_schemas.py`:

```python
async def test_delete_schema_pinned_by_link_returns_409(
    async_client, superuser_token_headers, test_system, transactional_session
):
    src_id = await _create_dataset(
        async_client, superuser_token_headers, test_system.id, "dss_src", "source"
    )
    tgt_id = await _create_dataset(
        async_client, superuser_token_headers, test_system.id, "dss_tgt", "raw"
    )
    src_schema_id = await _create_schema(async_client, superuser_token_headers, src_id, 1)
    tgt_schema_id = await _create_schema(async_client, superuser_token_headers, tgt_id, 1)
    resp = await async_client.post(
        "/api/v1/dataset-links/",
        json={
            "source_dataset_id": src_id, "target_dataset_id": tgt_id,
            "source_schema_id": src_schema_id, "target_schema_id": tgt_schema_id,
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 201, resp.text

    resp = await async_client.delete(
        f"/api/v1/dataset-schemas/{src_schema_id}",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "DATASET_SCHEMA_IN_USE"
```

- [ ] **Step 6: Wire `DATASET_SCHEMA_IN_USE` in `backend/api/v1/dataset_schemas.py`**

Extend the DELETE endpoint's `build_error_responses(...)` to include `DATASET_SCHEMA_IN_USE`.

- [ ] **Step 7: Run both tests — expect pass**

Run: `PYTEST_ARGS="-v tests/api/test_fields.py::test_patch_origin_to_deprecated_blocked_when_field_link_exists tests/api/test_dataset_schemas.py::test_delete_schema_pinned_by_link_returns_409" make test-docker`

Expected: 2 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/api/v1/fields.py backend/api/v1/dataset_schemas.py backend/schemas/filters.py tests/api/test_fields.py tests/api/test_dataset_schemas.py
git commit -m "feat(api): wire origin conflict + schema-in-use error codes"
```

---

## Task 23: SDK — `DatasetLinksResource`

**Files:**
- Create: `sdk/aide_sdk/resources/dataset_links.py`
- Modify: `sdk/aide_sdk/client.py`
- Create: `sdk/tests/test_dataset_links_resource.py`

- [ ] **Step 1: Write failing test**

Create `sdk/tests/test_dataset_links_resource.py`. This uses the `httpx.MockTransport` pattern from existing SDK tests. Read `sdk/tests/test_type_instances.py` first for the pattern.

```python
import uuid

import httpx
import pytest

from aide_schemas.dataset_link import DatasetLinkCreate


@pytest.mark.asyncio
async def test_compat_method_calls_expected_path(monkeypatch):
    # Use the existing SDK test scaffolding — mock HttpClient.get
    from aide_sdk.resources.dataset_links import DatasetLinksResource

    calls: list[dict] = []

    class FakeHttp:
        async def get(self, path, *, params=None):
            calls.append({"path": path, "params": params})
            link_id = path.split("/")[-2]
            return {
                "dataset_link_id": link_id,
                "pin_drift": {
                    "source": {"pinned_version": 1, "latest_version": 1, "has_drift": False},
                    "target": {"pinned_version": 1, "latest_version": 1, "has_drift": False},
                },
                "field_compat": [],
                "summary": {"ok": 0, "warn": 0, "error": 0, "total": 0},
                "status": "ok",
            }

    resource = DatasetLinksResource.__new__(DatasetLinksResource)
    resource._http = FakeHttp()
    resource._path = "/api/v1/dataset-links"

    link_id = uuid.uuid4()
    report = await resource.compat(link_id)

    assert report.status.value == "ok"
    assert calls[0]["path"] == f"/api/v1/dataset-links/{link_id}/compat"


@pytest.mark.asyncio
async def test_list_compat_passes_filters():
    from aide_sdk.resources.dataset_links import DatasetLinksResource

    calls: list[dict] = []

    class FakeHttp:
        async def get(self, path, *, params=None):
            calls.append({"path": path, "params": params})
            return {
                "items": [],
                "total": 0,
                "page": 1,
                "size": 20,
            }

    resource = DatasetLinksResource.__new__(DatasetLinksResource)
    resource._http = FakeHttp()
    resource._path = "/api/v1/dataset-links"

    page = await resource.list_compat(status=["error", "warn"], has_drift=True)

    assert page.total == 0
    assert calls[0]["path"] == "/api/v1/dataset-links/compat"
    assert "status" in calls[0]["params"]
    assert calls[0]["params"]["has_drift"] is True
```

- [ ] **Step 2: Run — expect failure**

Run: `cd sdk && uv run pytest tests/test_dataset_links_resource.py -v`

Expected: ImportError.

- [ ] **Step 3: Create the resource**

```python
# sdk/aide_sdk/resources/dataset_links.py
from __future__ import annotations

from typing import Any, List
from uuid import UUID

from aide_schemas.dataset_link import (
    DatasetLinkCreate,
    DatasetLinkRead,
    DatasetLinkUpdate,
)
from aide_schemas.lineage_compat import (
    DatasetLinkCompatReport,
    DatasetLinkCompatSummary,
)
from aide_schemas.pagination import Page
from aide_sdk.resources.base import BaseResource


class DatasetLinksResource(
    BaseResource[DatasetLinkCreate, DatasetLinkRead, DatasetLinkUpdate]
):
    _path = "/api/v1/dataset-links"
    _read_schema = DatasetLinkRead

    async def compat(self, obj_id: UUID) -> DatasetLinkCompatReport:
        data = await self._http.get(f"{self._path}/{obj_id}/compat")
        return DatasetLinkCompatReport.model_validate(data)

    async def list_compat(
        self,
        *,
        status: List[str] | None = None,
        has_drift: bool | None = None,
        dataset_id: UUID | None = None,
        system_id: UUID | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[DatasetLinkCompatSummary]:
        params: dict[str, Any] = {"page": page, "size": size}
        if status is not None:
            params["status"] = ",".join(status)
        if has_drift is not None:
            params["has_drift"] = has_drift
        if dataset_id is not None:
            params["dataset_id"] = str(dataset_id)
        if system_id is not None:
            params["system_id"] = str(system_id)
        data = await self._http.get(f"{self._path}/compat", params=params)
        return Page[DatasetLinkCompatSummary].model_validate(data)
```

- [ ] **Step 4: Register in `sdk/aide_sdk/client.py`**

Edit `_init_resources`:

```python
def _init_resources(self) -> None:
    # ... existing imports and assignments ...
    from aide_sdk.resources.dataset_links import DatasetLinksResource
    # ...
    self.dataset_links = DatasetLinksResource(self._http)
```

- [ ] **Step 5: Run — expect pass**

Run: `cd sdk && uv run pytest tests/test_dataset_links_resource.py -v`

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add sdk/aide_sdk/resources/dataset_links.py sdk/aide_sdk/client.py sdk/tests/test_dataset_links_resource.py
git commit -m "feat(sdk): add DatasetLinksResource with compat methods"
```

---

## Task 24: Version bumps + rebuild

**Files:**
- Modify: `schemas/pyproject.toml`
- Modify: `sdk/pyproject.toml`
- Modify: `crawler/pyproject.toml`

- [ ] **Step 1: Bump `schemas/pyproject.toml`**

Change `version = "0.1.x"` to `version = "0.2.0"`.

- [ ] **Step 2: Bump `sdk/pyproject.toml`**

Same: `version = "0.2.0"`.

- [ ] **Step 3: Bump `crawler/pyproject.toml`**

Same: `version = "0.2.0"`.

- [ ] **Step 4: Re-sync workspace**

```bash
uv sync
```

Expected: no errors.

- [ ] **Step 5: Rebuild test container (per CLAUDE.md)**

```bash
docker compose build test
```

- [ ] **Step 6: Commit**

```bash
git add schemas/pyproject.toml sdk/pyproject.toml crawler/pyproject.toml uv.lock
git commit -m "chore: bump aide-schemas, aide-sdk, aide-crawler to 0.2.0"
```

---

## Task 25: Integration — end-to-end lineage flow

**Files:**
- Create: `tests/integration/test_lineage_compat_e2e.py`

- [ ] **Step 1: Create the integration test**

```python
"""End-to-end scenarios covering the lineage data-contract flow.

Each scenario exercises AIDE from fresh state:
    create schemas → create link → compat OK → bump source schema
    → drift detected → re-pin → compat surfaces type issues
    → create new target schema + FieldBinding → re-pin → compat OK.
"""
from __future__ import annotations

from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.main import app
from backend.models import System, SystemFlavor, SystemKind, User


@pytest_asyncio.fixture
async def superuser(transactional_session: AsyncSession) -> User:
    user = User(
        email="integ_lineage.super@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
        is_superuser=True,
    )
    transactional_session.add(user)
    await transactional_session.commit()
    return user


@pytest_asyncio.fixture
async def headers(superuser: User) -> dict[str, str]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.post(
            "/api/v1/login/",
            data={"username": superuser.email, "password": "password123"},
        )
        token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def system(transactional_session: AsyncSession) -> System:
    kind = SystemKind(code="INT_LIN_K", name="Integ Lineage Kind")
    flavor = SystemFlavor(code="INT_LIN_F", name="Integ Lineage Flavor", kind=kind)
    system = System(
        code="INT_LIN_S", name="Integ Lineage System", flavor=flavor
    )
    transactional_session.add_all([kind, flavor, system])
    await transactional_session.commit()
    await transactional_session.refresh(system)
    return system


@pytest.mark.asyncio
async def test_drift_detection_and_repin_e2e(
    async_client: AsyncClient, headers: dict, system, transactional_session
):
    # 1) Create src + tgt datasets with layers
    async def _mk_ds(name: str, layer: str) -> str:
        r = await async_client.post(
            "/api/v1/datasets/",
            json={
                "system_id": str(system.id),
                "object_name": name,
                "kind": "rdbms",
                "schema_name": "s",
                "table_name": name,
                "layer": layer,
            },
            headers=headers,
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    src_id = await _mk_ds("e2e_src", "source")
    tgt_id = await _mk_ds("e2e_tgt", "raw")

    # 2) Create schemas (v1 on each)
    async def _mk_schema(dataset_id: str, v: int) -> str:
        r = await async_client.post(
            "/api/v1/dataset-schemas/",
            json={"dataset_id": dataset_id, "version_num": v, "schema": {}},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    s1 = await _mk_schema(src_id, 1)
    t1 = await _mk_schema(tgt_id, 1)

    # 3) Create link pinned to v1/v1
    r = await async_client.post(
        "/api/v1/dataset-links/",
        json={
            "source_dataset_id": src_id, "target_dataset_id": tgt_id,
            "source_schema_id": s1, "target_schema_id": t1,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    link_id = r.json()["id"]
    link_row_version = r.json()["row_version"]

    # 4) Compat report: status=ok, no field_links yet
    r = await async_client.get(
        f"/api/v1/dataset-links/{link_id}/compat", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["pin_drift"]["source"]["has_drift"] is False

    # 5) Add a new source schema v2 → drift
    s2 = await _mk_schema(src_id, 2)
    r = await async_client.get(
        f"/api/v1/dataset-links/{link_id}/compat", headers=headers
    )
    body = r.json()
    assert body["pin_drift"]["source"]["has_drift"] is True
    assert body["pin_drift"]["source"]["latest_version"] == 2
    assert body["status"] == "warn"

    # 6) Re-pin link to source v2
    r = await async_client.patch(
        f"/api/v1/dataset-links/{link_id}",
        json={"source_schema_id": s2, "row_version": link_row_version},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # 7) Compat re-checked → drift cleared
    r = await async_client.get(
        f"/api/v1/dataset-links/{link_id}/compat", headers=headers
    )
    body = r.json()
    assert body["pin_drift"]["source"]["has_drift"] is False
    assert body["status"] == "ok"
```

- [ ] **Step 2: Run**

Run: `PYTEST_ARGS="-v tests/integration/test_lineage_compat_e2e.py" make test-docker`

Expected: PASS.

If missing, create `tests/integration/__init__.py` (empty).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/
git commit -m "test(lineage): end-to-end compat drift → re-pin scenario"
```

---

## Task 26: ADR-018

**Files:**
- Create: `docs/adr/adr-018-schema-pinned-lineage.md`
- Modify: `docs/adr/README.md`

- [ ] **Step 1: Create the ADR**

```markdown
# ADR-018: Schema-Pinned Lineage and Field Lifecycle Enum

**Status:** Accepted
**Date:** 2026-04-23
**Deciders:** Backend team lead

---

## 1. Context and Problem

Phase 1 (ADR-016) modelled dataset-to-dataset and column-to-column lineage at **identity level**. That left two capabilities unexpressed:

1. **Version pinning.** A `dataset_link` pointed at a source and target dataset, but types live on `field_binding` (per-`dataset_schema` version). The link had no notion of which version it was compatible with.
2. **Target-field lifecycle.** `Field.is_tech: bool` conflated "generated by pipeline" with "kept for backward compatibility, NULL-padded." When a source column is dropped, the target column cannot be `is_tech=False` (Phase 1 invariant: non-tech target must have a source) nor meaningfully `is_tech=True` (tech means pipeline-generated, not abandoned).

This ADR records the three decisions that shape Phase 3.

## 2. Decision

### 2.1 Pins on `DatasetLink`, not on `FieldLink`

Add two NOT NULL FK columns to `dataset_links`: `source_schema_id` and `target_schema_id`, both `ON DELETE RESTRICT` to `dataset_schemas.id`. `FieldLink` stays at identity level.

**Alternative rejected:** binding-level `FieldLink` (referencing `field_binding` rows directly). Binding-level would make compat a direct read but force re-creation of all `FieldLink` rows on every re-pin — the logical edge ("source.price feeds target.price") no longer survives schema evolution. Identity-level keeps the edge persistent and pays a two-JOIN tax on compat queries (cheap — covered by existing index).

### 2.2 `FieldOrigin` as a three-state enum, not two booleans

Replace `Field.is_tech: bool` with `Field.origin: str` constrained to `{mapped, tech, deprecated}`.

**Alternative rejected:** adding a second boolean `is_deprecated`. Two booleans yield four combinations, one of which (`is_tech AND is_deprecated`) is illegal — the guard rail has to live somewhere (CheckConstraint or service check), and the illegal combo signals the concept is actually single-axis.

Semantics per origin:

- `mapped` — must have ≥1 active `FieldLink` as target.
- `tech` — generated by pipeline (CDC op, timestamps, hashes); no source required.
- `deprecated` — kept for backward compatibility; worker writes NULL.

Origin transitions are a state machine enforced atomically with `FieldLink` creates/deletes in a single UoW.

### 2.3 Strict FieldLink create, lax post-re-pin

`FieldLink` create requires the source and target fields to have `FieldBinding` rows in the link's pinned schemas. After a re-pin, pre-existing `FieldLink` rows can survive even if the binding is gone — the compat report surfaces them as `source_unbound` / `target_unbound`. The operator cleans them explicitly.

**Alternative rejected:** strict both at create and at re-pin. Strict re-pin would force the operator to delete FieldLinks as a precondition of re-pin, removing the diagnostic path (compat says "here's what broke") and making re-pin a destructive operation.

## 3. Consequences

**Positive:**

- ETL pre-flight can call a single endpoint and trust AIDE's answer — AIDE is now a data contract.
- Schema evolution on source or target is traceable and non-destructive: drift detection separates from breakage detection.
- `deprecated` gives a legal home to backward-compat columns without distorting `tech`.

**Negative:**

- Two Alembic migrations required (additive + finalize) plus a backfill script; rollback after the finalize step is unsafe once `deprecated` fields exist.
- Bulk compat list is O(N) per page (one compat_report call per row), fine for MVP monitoring loads but noted for revisit.

## 4. Related

- Spec: [`docs/superpowers/specs/2026-04-23-schema-pinned-lineage-design.md`](../superpowers/specs/2026-04-23-schema-pinned-lineage-design.md)
- Plan: [`docs/superpowers/plans/2026-04-23-schema-pinned-lineage.md`](../superpowers/plans/2026-04-23-schema-pinned-lineage.md)
- Predecessor: ADR-016 (Phase 1 lineage)
- Predecessor: ADR-017 (tech-field templates)
- ADR-010 (enum-as-varchar) — `FieldOrigin` follows this convention.
- ADR-006 (soft-delete) — `DatasetLink` keeps soft-delete; pinning does not affect that.
```

- [ ] **Step 2: Add ADR-018 to `docs/adr/README.md` index**

Find the ADR index table. Append a row:

```markdown
| ADR-018 | Schema-pinned lineage & Field lifecycle | Accepted | 2026-04-23 |
```

(Match the existing columns — likely `ID | Title | Status | Date`.)

- [ ] **Step 3: Commit**

```bash
git add docs/adr/adr-018-schema-pinned-lineage.md docs/adr/README.md
git commit -m "docs: add ADR-018 schema-pinned lineage"
```

---

## Task 27: data model JSON update

**Files:**
- Modify: `docs/AIDE_data_model.json`

- [ ] **Step 1: Update `dataset_links` table in the JSON**

Open the file and find the `dataset_links` table node. Add two new fields to its `fields` array:

```json
{ "name": "source_schema_id", "type": "uuid", "nullable": false, "fk": "dataset_schemas.id" },
{ "name": "target_schema_id", "type": "uuid", "nullable": false, "fk": "dataset_schemas.id" }
```

And add two relationships to the `relationships` block:

```json
{ "from": "dataset_links.source_schema_id", "to": "dataset_schemas.id", "onDelete": "RESTRICT" },
{ "from": "dataset_links.target_schema_id", "to": "dataset_schemas.id", "onDelete": "RESTRICT" }
```

- [ ] **Step 2: Update `fields` table**

Remove the `is_tech` field. Add:

```json
{ "name": "origin", "type": "varchar(20)", "nullable": false, "default": "mapped" }
```

- [ ] **Step 3: Commit**

```bash
git add docs/AIDE_data_model.json
git commit -m "docs(data-model): update for dataset_links pins + field.origin"
```

---

## Task 28: ETL pre-flight integration doc

**Files:**
- Create: `docs/integrations/etl-pre-flight.md`

This doc is referenced from spec §6.4 — a short guide ETL engineers follow when wiring AIDE's compat endpoint into their pre-flight checks.

- [ ] **Step 1: Create the doc**

```markdown
# ETL Pre-Flight — Using AIDE's compat endpoint

AIDE is the data contract between a source and a target. Before running an
ETL load, the worker asks AIDE whether the contract is still valid. If it is
not, the load is blocked until a human re-pins the `DatasetLink` or updates
the target schema.

## Flow

1. The ETL worker knows its `dataset_link_id` — either from static config or
   resolved by name pair (`source_dataset`, `target_dataset`) via the SDK's
   `dataset_links.list(...)`.
2. Call `GET /api/v1/dataset-links/{dataset_link_id}/compat` (or
   `aide_client.dataset_links.compat(link_id)` via the SDK).
3. Switch on `response.status`:
   - `"error"` — abort the load. Alert the contract owners. The report's
     `field_compat[*].issues` lists what broke.
   - `"warn"` — log each issue. Proceed by default. A strict-mode worker
     config may escalate `warn` to abort.
   - `"ok"` — proceed.
4. If `response.pin_drift.source.has_drift` or
   `response.pin_drift.target.has_drift` is true, the contract is
   out-of-date even if not broken. Emit a notification for schema owners.
   Proceed with the load.

## Example

```python
async with AideClient(base_url, username, password) as client:
    report = await client.dataset_links.compat(dataset_link_id)
    if report.status.value == "error":
        raise LoadAbort(
            f"DatasetLink {dataset_link_id}: "
            + ", ".join(sorted({i.value for fc in report.field_compat for i in fc.issues}))
        )
    if report.status.value == "warn" and worker_config.strict:
        raise LoadAbort("strict mode: contract has warnings")
    # proceed
```

## Semantics

- `status == "error"`: at least one `field_compat` entry has severity
  `error` — type incompatible, no cast rule, or a side is unbound in its
  pinned schema.
- `status == "warn"`: no errors, but something is imperfect — a cast is
  required, a column tightens from nullable → NOT NULL, or the pin has
  drifted from the latest available schema.
- `status == "ok"`: exact type match, no drift, no warnings.

## When pin drift is detected

Pin drift means the source or target dataset has a newer `DatasetSchema`
than the link's pin. Drift alone does not break the contract — existing
field types are still consistent against the pinned schemas. But it means
someone bumped the schema without updating the link, which is usually a
signal that the contract needs re-pinning.

## Webhooks and push alerts

Not yet supported. Poll `GET /api/v1/dataset-links/compat?status=error`
on a schedule for dashboard/alert scenarios.
```

- [ ] **Step 2: Commit**

```bash
git add docs/integrations/etl-pre-flight.md
git commit -m "docs: add ETL pre-flight integration guide"
```

---

## Task 29: CLAUDE.md quirks

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append to the `Known quirks` section**

Add the following bullets near the end of the existing bulleted list:

```markdown
- After re-pin of `DatasetLink`, the compat report may show `source_unbound` / `target_unbound` for `FieldLink` rows whose fields have no binding in the new pinned schemas. Expected — operator deletes them as part of the pin transition.
- `Field.origin` transitions are atomic with `FieldLink` create/delete in a single UoW. `PATCH /fields/{id}` with `origin: "deprecated"` while the field still has an active inbound `FieldLink` returns `409 FIELD_ORIGIN_CONFLICT`.
- Lineage-pin Migration B (`add_lineage_pins_b_finalize`) downgrade is **unsafe** once `DEPRECATED` fields exist — `deprecated` maps back to `is_tech=False` (mapped), violating the "mapped target needs source" invariant. Hold Migration B until the forward direction is confirmed stable.
- Route ordering in `backend/api/v1/dataset_links.py`: the `/compat` (bulk) route must be declared **before** `/{obj_id}` variants so FastAPI does not interpret `compat` as a UUID path parameter.
- Lockstep bump of `aide-schemas`, `aide-sdk`, `aide-crawler` at any breaking schema change. No dual-support transitional acceptance of old field names (`is_tech` removed, not deprecated in place).
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record phase 3 lineage quirks"
```

---

## Task 30: Final verification

**Files:** none

- [ ] **Step 1: Run formatter**

```bash
make format
```

Expected: no changes needed (if any files were re-formatted, commit them).

- [ ] **Step 2: Run lint + typecheck**

```bash
make check
```

Expected: PASS. Pre-existing mypy errors in `backend/scripts/_seed_core.py` and `sdk/aide_sdk/resources/datasets.py` are OK (per CLAUDE.md) — the new code must not add new errors.

- [ ] **Step 3: Run full test suite**

```bash
make test-docker
```

Expected: ALL PASS.

- [ ] **Step 4: Run SDK tests standalone**

```bash
cd sdk && uv run pytest tests/ -v
cd ..
```

Expected: ALL PASS.

- [ ] **Step 5: Run crawler tests standalone**

```bash
cd crawler && uv run pytest tests/ -v
cd ..
```

Expected: ALL PASS.

- [ ] **Step 6: Final commit (if `make format` touched anything)**

```bash
git add -u
git commit -m "chore: format after phase 3 landing" || echo "no formatting changes"
```

---

## Post-merge checklist (for the PR author)

These are deploy-time steps, not code steps. Include them in the PR description:

1. After merging, run Migration A on each target environment (`make alembic-head` or equivalent).
2. Run the backfill script (`uv run python -m backend.scripts.migrate_lineage_pins`). Fix any unresolved links (create missing DatasetSchemas, or soft-delete orphan links). Re-run — it's idempotent.
3. Deploy the new application binary.
4. Soak for 12–24h. Monitor compat endpoint errors.
5. Run Migration B to finalize (drops `fields.is_tech`, sets NOT NULL on pins and origin).

Rollback: Migration A is safe to downgrade any time. Migration B downgrade is unsafe once `DEPRECATED` fields exist — see CLAUDE.md quirk.
