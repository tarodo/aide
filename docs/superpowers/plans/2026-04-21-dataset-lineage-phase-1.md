# Dataset Lineage (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dataset-to-dataset and column-to-column lineage across layers (source → cdc → kafka → raw → core). Introduce `is_tech` on Field and `pattern_code` on Dataset. Phase 2 (tech-field templates) will be a separate plan.

**Architecture:** Two new tables — `dataset_links` (soft-delete, SoftDeleteMetaDataMixin, unique `(source, target)` among active, layer-order validation) and `field_links` (hard-delete, child of dataset_links via FK CASCADE, target exclusivity inside a link, source reuse allowed for fanout). Both sit behind standard AIDE layers: Router → Service → UoW → Repository → Model. Deletion strategy: block Dataset delete when any active dataset_link exists; `ON DELETE CASCADE` on all field_link FKs keeps the graph consistent when a Field is removed.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, pytest + pytest-asyncio. Tests run inside Docker (`make test-docker`); narrow with `PYTEST_ARGS="-v tests/path/to/file.py"`.

**Spec:** `docs/superpowers/specs/2026-04-21-dataset-lineage-design.md`

---

## File Map

**Modified:**
- `schemas/aide_schemas/dataset.py` — add `DatasetLayer`, `DatasetPattern` enums + `LAYER_ORDER`, tighten `layer` type, add `pattern_code`
- `schemas/aide_schemas/field.py` — add `is_tech: bool`
- `backend/schemas/dataset.py`, `backend/schemas/field.py` — re-export new names
- `backend/models/dataset.py` — `pattern_code` column
- `backend/models/field.py` — `is_tech` column
- `backend/models/__init__.py` — register new models
- `backend/core/errors.py` — add new error codes + ERROR_MAP entries
- `backend/db/uow.py` — register `dataset_links`, `field_links`
- `backend/services/dataset.py` — `_pre_delete` blocks on active links
- `backend/services/field.py` — `_pre_update` rejects `is_tech=False` without inbound links
- `backend/api/v1/datasets.py` — `upstream-links`, `downstream-links`, `unmapped-fields` endpoints
- `backend/main.py` — include new routers
- `docs/AIDE_data_model.json` — add new tables/FKs
- `docs/adr/README.md` — add ADR-016 row

**Created:**
- `backend/models/dataset_link.py`
- `backend/models/field_link.py`
- `schemas/aide_schemas/dataset_link.py`
- `schemas/aide_schemas/field_link.py`
- `backend/schemas/dataset_link.py`, `backend/schemas/field_link.py`
- `backend/repositories/dataset_link.py`, `backend/repositories/field_link.py`
- `backend/services/dataset_link.py`, `backend/services/field_link.py`
- `backend/api/v1/dataset_links.py`, `backend/api/v1/field_links.py`
- `backend/alembic/versions/NNNN_add_pattern_code_to_datasets.py`
- `backend/alembic/versions/NNNN_add_is_tech_to_fields.py`
- `backend/alembic/versions/NNNN_create_dataset_links.py`
- `backend/alembic/versions/NNNN_create_field_links.py`
- `tests/models/test_dataset_link.py`, `tests/models/test_field_link.py`
- `tests/repositories/test_dataset_link_repository.py`, `tests/repositories/test_field_link_repository.py`
- `tests/services/test_dataset_link_service.py`, `tests/services/test_field_link_service.py`
- `tests/api/test_dataset_links.py`, `tests/api/test_field_links.py`
- `docs/adr/adr-016-dataset-lineage.md`

Each file has one responsibility. Tests mirror their production counterparts.

---

## Task 1: Enums + error codes

**Files:**
- Modify: `schemas/aide_schemas/dataset.py`
- Modify: `backend/core/errors.py`
- Test: `tests/api/test_datasets.py` (check existing tests still pass with `layer` as enum)

- [ ] **Step 1: Add enums to `schemas/aide_schemas/dataset.py`**

Add near top of file (after imports, before `DatasetBase`):

```python
import enum


class DatasetLayer(str, enum.Enum):
    SOURCE = "source"
    CDC = "cdc"
    KAFKA = "kafka"
    RAW = "raw"
    CORE = "core"


LAYER_ORDER: dict[DatasetLayer, int] = {
    DatasetLayer.SOURCE: 0,
    DatasetLayer.CDC: 1,
    DatasetLayer.KAFKA: 2,
    DatasetLayer.RAW: 3,
    DatasetLayer.CORE: 4,
}


class DatasetPattern(str, enum.Enum):
    SCD1 = "scd1"
    SCD2 = "scd2"
    SNAPSHOT = "snapshot"
    APPEND_ONLY = "append_only"
    CDC_PAYLOAD = "cdc_payload"
```

Change `DatasetBase.layer` from `str | None` to `DatasetLayer | None`:

```python
class DatasetBase(BaseModel):
    system_id: uuid.UUID
    object_name: str
    layer: DatasetLayer | None = None
    is_active: bool = True
    extra: dict[str, Any] | None = None
```

**Note:** `pattern_code` is NOT added to `DatasetBase` in this task. It is added in Task 3 together with the `pattern_code` model column and the Alembic migration. Adding the schema field before the column exists would break `DatasetService.create` (the service passes `**obj_in.model_dump()` to the SQLAlchemy model constructor; an unknown kwarg raises `TypeError`).

- [ ] **Step 2: Add error codes to `backend/core/errors.py`**

Add to constants section:

```python
DATASET_LINK_NOT_FOUND = "DATASET_LINK_NOT_FOUND"
DATASET_LINK_ALREADY_EXISTS = "DATASET_LINK_ALREADY_EXISTS"
DATASET_LINK_SELF_REFERENCE = "DATASET_LINK_SELF_REFERENCE"
DATASET_LINK_LAYER_ORDER = "DATASET_LINK_LAYER_ORDER"
DATASET_LINK_LAYER_MISSING = "DATASET_LINK_LAYER_MISSING"
DATASET_HAS_ACTIVE_LINKS = "DATASET_HAS_ACTIVE_LINKS"
FIELD_LINK_NOT_FOUND = "FIELD_LINK_NOT_FOUND"
FIELD_LINK_ALREADY_EXISTS = "FIELD_LINK_ALREADY_EXISTS"
FIELD_LINK_SOURCE_DATASET_MISMATCH = "FIELD_LINK_SOURCE_DATASET_MISMATCH"
FIELD_LINK_TARGET_DATASET_MISMATCH = "FIELD_LINK_TARGET_DATASET_MISMATCH"
FIELD_LINK_TARGET_OCCUPIED = "FIELD_LINK_TARGET_OCCUPIED"
FIELD_NON_TECH_REQUIRES_SOURCE = "FIELD_NON_TECH_REQUIRES_SOURCE"
```

Add corresponding entries to `ERROR_MAP`:

```python
DATASET_LINK_NOT_FOUND: (status.HTTP_404_NOT_FOUND, "The requested dataset link was not found."),
DATASET_LINK_ALREADY_EXISTS: (status.HTTP_409_CONFLICT, "An active dataset link between this source and target already exists."),
DATASET_LINK_SELF_REFERENCE: (status.HTTP_400_BAD_REQUEST, "A dataset cannot link to itself."),
DATASET_LINK_LAYER_ORDER: (status.HTTP_400_BAD_REQUEST, "Target dataset layer must come after source layer."),
DATASET_LINK_LAYER_MISSING: (status.HTTP_400_BAD_REQUEST, "Both source and target datasets must have a layer set."),
DATASET_HAS_ACTIVE_LINKS: (status.HTTP_409_CONFLICT, "Dataset has active lineage links; unlink first."),
FIELD_LINK_NOT_FOUND: (status.HTTP_404_NOT_FOUND, "The requested field link was not found."),
FIELD_LINK_ALREADY_EXISTS: (status.HTTP_409_CONFLICT, "A field link with this source and target already exists in this dataset link."),
FIELD_LINK_SOURCE_DATASET_MISMATCH: (status.HTTP_400_BAD_REQUEST, "Source field does not belong to the source dataset."),
FIELD_LINK_TARGET_DATASET_MISMATCH: (status.HTTP_400_BAD_REQUEST, "Target field does not belong to the target dataset."),
FIELD_LINK_TARGET_OCCUPIED: (status.HTTP_409_CONFLICT, "Target field already has a source mapping in this dataset link."),
FIELD_NON_TECH_REQUIRES_SOURCE: (status.HTTP_409_CONFLICT, "Non-technical field must have at least one inbound field link."),
```

- [ ] **Step 3: Run existing dataset tests to catch enum-tightening regressions**

```bash
PYTEST_ARGS="-v tests/api/test_datasets.py tests/services/test_dataset_service.py" make test-docker
```

Expected: PASS (existing tests pass `layer` as `"source"`, `"raw"`, etc. — valid enum members). If any test passes a non-enum value (e.g. `"staging"`), update it to a valid `DatasetLayer` value. Do not relax the enum.

- [ ] **Step 4: Format + commit**

```bash
make format
git add schemas/aide_schemas/dataset.py backend/core/errors.py tests/
git commit -m "feat: add lineage enums and error codes"
```

---

## Task 2: Field.is_tech column + migration

**Files:**
- Modify: `backend/models/field.py`
- Modify: `schemas/aide_schemas/field.py`
- Create: `backend/alembic/versions/XXXX_add_is_tech_to_fields.py`
- Test: `tests/repositories/test_field_repository.py` (add a test)

- [ ] **Step 1: Write the failing test in `tests/repositories/test_field_repository.py`**

Add to the existing test file:

```python
async def test_field_is_tech_default_false(
    transactional_session: AsyncSession, seeded_system: System
):
    dataset = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="t",
        kind="rdbms",
        schema_name="s",
        table_name="t",
    )
    transactional_session.add(dataset)
    await transactional_session.flush()
    field = Field(dataset_id=dataset.id, name="c")
    transactional_session.add(field)
    await transactional_session.flush()
    await transactional_session.refresh(field)
    assert field.is_tech is False


async def test_field_is_tech_persists_true(
    transactional_session: AsyncSession, seeded_system: System
):
    dataset = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="t2",
        kind="rdbms",
        schema_name="s",
        table_name="t2",
    )
    transactional_session.add(dataset)
    await transactional_session.flush()
    field = Field(dataset_id=dataset.id, name="etl_ts", is_tech=True)
    transactional_session.add(field)
    await transactional_session.flush()
    await transactional_session.refresh(field)
    assert field.is_tech is True
```

Use existing fixtures/imports from the same file; if `seeded_system` doesn't exist yet, inspect `tests/repositories/test_field_repository.py` and reuse the same fixture pattern that existing tests employ (they create a System + Dataset inline).

- [ ] **Step 2: Run test to verify failure**

```bash
PYTEST_ARGS="-v tests/repositories/test_field_repository.py::test_field_is_tech_default_false" make test-docker
```

Expected: FAIL with `AttributeError: 'Field' object has no attribute 'is_tech'` or similar.

- [ ] **Step 3: Add `is_tech` to `backend/models/field.py`**

In the `Field` class body, after `extra: Mapped[dict[str, Any] | None] = ...`:

```python
is_tech: Mapped[bool] = mapped_column(
    Boolean, nullable=False, default=False, server_default=text("false")
)
```

Add imports at the top if missing: `from sqlalchemy import Boolean, text`.

- [ ] **Step 4: Add `is_tech` to `schemas/aide_schemas/field.py`**

Update `FieldBase`:

```python
class FieldBase(BaseModel):
    dataset_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    name: str
    path: str | None = None
    extra: dict[str, Any] | None = None
    is_tech: bool = False
```

Update `FieldUpdate`:

```python
class FieldUpdate(VersionedUpdateMixin, NoteMixin):
    dataset_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    name: str | None = None
    path: str | None = None
    extra: dict[str, Any] | None = None
    is_tech: bool | None = None
```

Update `FieldTree` to include `is_tech: bool`.

- [ ] **Step 5: Generate the migration**

```bash
make alembic-gen
```

Then open the newest file under `backend/alembic/versions/`, verify it contains only the `is_tech` column addition. Strip any unrelated auto-generated operations. The body should look like:

```python
def upgrade() -> None:
    op.add_column(
        "fields",
        sa.Column(
            "is_tech",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("fields", "is_tech")
```

Rename the file if needed to a descriptive slug like `NNNN_add_is_tech_to_fields.py`.

- [ ] **Step 6: Run test to verify pass**

```bash
PYTEST_ARGS="-v tests/repositories/test_field_repository.py" make test-docker
```

Expected: PASS for both new tests and all existing tests.

- [ ] **Step 7: Format + commit**

```bash
make format
git add backend/models/field.py schemas/aide_schemas/field.py \
    backend/alembic/versions/ tests/repositories/test_field_repository.py
git commit -m "feat(field): add is_tech column"
```

---

## Task 3: Dataset.pattern_code column + migration + schema

**Files:**
- Modify: `backend/models/dataset.py`
- Modify: `schemas/aide_schemas/dataset.py`
- Create: `backend/alembic/versions/XXXX_add_pattern_code_to_datasets.py`
- Test: `tests/repositories/test_dataset_repository.py`

- [ ] **Step 1: Write the failing test in `tests/repositories/test_dataset_repository.py`**

```python
async def test_dataset_pattern_code_roundtrip(
    transactional_session: AsyncSession, seeded_system: System
):
    ds = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="pc_rt",
        kind="rdbms",
        schema_name="s",
        table_name="pc_rt",
        pattern_code="scd2",
    )
    transactional_session.add(ds)
    await transactional_session.flush()
    await transactional_session.refresh(ds)
    assert ds.pattern_code == "scd2"
```

- [ ] **Step 2: Run to verify FAIL**

```bash
PYTEST_ARGS="-v tests/repositories/test_dataset_repository.py::test_dataset_pattern_code_roundtrip" make test-docker
```

Expected: FAIL (`pattern_code` unknown).

- [ ] **Step 3: Add column to `backend/models/dataset.py`**

In the `Dataset` class body, after `kind`:

```python
pattern_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

- [ ] **Step 3b: Add `pattern_code` to Pydantic schemas in `schemas/aide_schemas/dataset.py`**

Update `DatasetBase` to include the new field (deferred from Task 1 — see Task 1 note):

```python
class DatasetBase(BaseModel):
    system_id: uuid.UUID
    object_name: str
    layer: DatasetLayer | None = None
    pattern_code: DatasetPattern | None = None
    is_active: bool = True
    extra: dict[str, Any] | None = None
```

This makes `pattern_code` available on every `DatasetXCreate`/`DatasetXRead` via inheritance.

- [ ] **Step 4: Generate migration**

```bash
make alembic-gen
```

Strip unrelated ops from the generated file. The body should contain exactly:

```python
def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("pattern_code", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("datasets", "pattern_code")
```

- [ ] **Step 5: Run test**

```bash
PYTEST_ARGS="-v tests/repositories/test_dataset_repository.py" make test-docker
```

Expected: PASS.

- [ ] **Step 6: Format + commit**

```bash
make format
git add backend/models/dataset.py schemas/aide_schemas/dataset.py \
    backend/alembic/versions/ tests/repositories/test_dataset_repository.py
git commit -m "feat(dataset): add pattern_code column"
```

---

## Task 4: DatasetLink model + migration

**Files:**
- Create: `backend/models/dataset_link.py`
- Modify: `backend/models/__init__.py`
- Create: `backend/alembic/versions/XXXX_create_dataset_links.py`
- Create: `tests/models/test_dataset_link.py`

- [ ] **Step 1: Write failing test in `tests/models/test_dataset_link.py`**

```python
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.system import System


@pytest.mark.asyncio
async def test_dataset_link_create(transactional_session: AsyncSession, seeded_system: System):
    src = DatasetRdbms(system_id=seeded_system.id, object_name="src", kind="rdbms", schema_name="s", table_name="src")
    tgt = DatasetRdbms(system_id=seeded_system.id, object_name="tgt", kind="rdbms", schema_name="s", table_name="tgt")
    transactional_session.add_all([src, tgt])
    await transactional_session.flush()

    link = DatasetLink(source_dataset_id=src.id, target_dataset_id=tgt.id)
    transactional_session.add(link)
    await transactional_session.flush()
    await transactional_session.refresh(link)

    assert link.id is not None
    assert link.row_version == 1
    assert link.deleted_at is None


@pytest.mark.asyncio
async def test_dataset_link_self_reference_rejected(
    transactional_session: AsyncSession, seeded_system: System
):
    ds = DatasetRdbms(system_id=seeded_system.id, object_name="self", kind="rdbms", schema_name="s", table_name="self")
    transactional_session.add(ds)
    await transactional_session.flush()

    link = DatasetLink(source_dataset_id=ds.id, target_dataset_id=ds.id)
    transactional_session.add(link)
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_dataset_link_pair_unique_active(
    transactional_session: AsyncSession, seeded_system: System
):
    a = DatasetRdbms(system_id=seeded_system.id, object_name="a", kind="rdbms", schema_name="s", table_name="a")
    b = DatasetRdbms(system_id=seeded_system.id, object_name="b", kind="rdbms", schema_name="s", table_name="b")
    transactional_session.add_all([a, b])
    await transactional_session.flush()
    transactional_session.add(DatasetLink(source_dataset_id=a.id, target_dataset_id=b.id))
    await transactional_session.flush()
    transactional_session.add(DatasetLink(source_dataset_id=a.id, target_dataset_id=b.id))
    with pytest.raises(IntegrityError):
        await transactional_session.flush()
```

Reuse `seeded_system` fixture from existing tests (`tests/repositories/test_dataset_repository.py` has the pattern).

- [ ] **Step 2: Run to verify FAIL**

```bash
PYTEST_ARGS="-v tests/models/test_dataset_link.py" make test-docker
```

Expected: ImportError on `backend.models.dataset_link`.

- [ ] **Step 3: Create `backend/models/dataset_link.py`**

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

    source_dataset = relationship("Dataset", foreign_keys=[source_dataset_id])
    target_dataset = relationship("Dataset", foreign_keys=[target_dataset_id])
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
            f"source={self.source_dataset_id}, target={self.target_dataset_id})"
        )
```

- [ ] **Step 4: Register in `backend/models/__init__.py`**

Add `from .dataset_link import DatasetLink as DatasetLink` and include `"DatasetLink"` in `__all__`.

- [ ] **Step 5: Generate migration**

```bash
make alembic-gen
```

Strip unrelated ops. Expected body:

```python
def upgrade() -> None:
    op.create_table(
        "dataset_links",
        sa.Column("source_dataset_id", sa.UUID(), nullable=False),
        sa.Column("target_dataset_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "source_dataset_id <> target_dataset_id", name="ck_dataset_link_no_self"
        ),
        sa.ForeignKeyConstraint(["source_dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["target_dataset_id"], ["datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dataset_links_id"), "dataset_links", ["id"], unique=True)
    op.create_index(op.f("ix_dataset_links_source_dataset_id"), "dataset_links", ["source_dataset_id"], unique=False)
    op.create_index(op.f("ix_dataset_links_target_dataset_id"), "dataset_links", ["target_dataset_id"], unique=False)
    op.create_index(op.f("ix_dataset_links_created_by"), "dataset_links", ["created_by"], unique=False)
    op.create_index(op.f("ix_dataset_links_updated_by"), "dataset_links", ["updated_by"], unique=False)
    op.create_index(op.f("ix_dataset_links_deleted_at"), "dataset_links", ["deleted_at"], unique=False)
    op.create_index(
        "uq_dataset_link_pair_active",
        "dataset_links",
        ["source_dataset_id", "target_dataset_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_dataset_link_pair_active", table_name="dataset_links")
    op.drop_index(op.f("ix_dataset_links_deleted_at"), table_name="dataset_links")
    op.drop_index(op.f("ix_dataset_links_updated_by"), table_name="dataset_links")
    op.drop_index(op.f("ix_dataset_links_created_by"), table_name="dataset_links")
    op.drop_index(op.f("ix_dataset_links_target_dataset_id"), table_name="dataset_links")
    op.drop_index(op.f("ix_dataset_links_source_dataset_id"), table_name="dataset_links")
    op.drop_index(op.f("ix_dataset_links_id"), table_name="dataset_links")
    op.drop_table("dataset_links")
```

- [ ] **Step 6: Run tests**

```bash
PYTEST_ARGS="-v tests/models/test_dataset_link.py" make test-docker
```

Expected: PASS (3 tests).

- [ ] **Step 7: Format + commit**

```bash
make format
git add backend/models/dataset_link.py backend/models/__init__.py \
    backend/alembic/versions/ tests/models/test_dataset_link.py
git commit -m "feat(lineage): add dataset_link model"
```

---

## Task 5: DatasetLink schemas + repository

**Files:**
- Create: `schemas/aide_schemas/dataset_link.py`
- Create: `backend/schemas/dataset_link.py`
- Create: `backend/repositories/dataset_link.py`
- Create: `tests/repositories/test_dataset_link_repository.py`

- [ ] **Step 1: Write failing repository test**

`tests/repositories/test_dataset_link_repository.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.system import System
from backend.repositories.dataset_link import DatasetLinkRepository


@pytest.mark.asyncio
async def test_has_active_links_for_dataset(
    transactional_session: AsyncSession, seeded_system: System
):
    src = DatasetRdbms(system_id=seeded_system.id, object_name="s", kind="rdbms", schema_name="s", table_name="s")
    tgt = DatasetRdbms(system_id=seeded_system.id, object_name="t", kind="rdbms", schema_name="s", table_name="t")
    transactional_session.add_all([src, tgt])
    await transactional_session.flush()

    repo = DatasetLinkRepository(transactional_session)
    assert await repo.has_active_links_for_dataset(src.id) is False

    link = DatasetLink(source_dataset_id=src.id, target_dataset_id=tgt.id)
    transactional_session.add(link)
    await transactional_session.flush()

    assert await repo.has_active_links_for_dataset(src.id) is True
    assert await repo.has_active_links_for_dataset(tgt.id) is True


@pytest.mark.asyncio
async def test_get_active_between(
    transactional_session: AsyncSession, seeded_system: System
):
    a = DatasetRdbms(system_id=seeded_system.id, object_name="a", kind="rdbms", schema_name="s", table_name="a")
    b = DatasetRdbms(system_id=seeded_system.id, object_name="b", kind="rdbms", schema_name="s", table_name="b")
    transactional_session.add_all([a, b])
    await transactional_session.flush()

    repo = DatasetLinkRepository(transactional_session)
    assert await repo.get_active_between(a.id, b.id) is None

    link = DatasetLink(source_dataset_id=a.id, target_dataset_id=b.id)
    transactional_session.add(link)
    await transactional_session.flush()

    found = await repo.get_active_between(a.id, b.id)
    assert found is not None and found.id == link.id


@pytest.mark.asyncio
async def test_list_by_source_and_target(
    transactional_session: AsyncSession, seeded_system: System
):
    a = DatasetRdbms(system_id=seeded_system.id, object_name="a1", kind="rdbms", schema_name="s", table_name="a1")
    b = DatasetRdbms(system_id=seeded_system.id, object_name="b1", kind="rdbms", schema_name="s", table_name="b1")
    c = DatasetRdbms(system_id=seeded_system.id, object_name="c1", kind="rdbms", schema_name="s", table_name="c1")
    transactional_session.add_all([a, b, c])
    await transactional_session.flush()
    transactional_session.add(DatasetLink(source_dataset_id=a.id, target_dataset_id=b.id))
    transactional_session.add(DatasetLink(source_dataset_id=a.id, target_dataset_id=c.id))
    transactional_session.add(DatasetLink(source_dataset_id=b.id, target_dataset_id=c.id))
    await transactional_session.flush()

    repo = DatasetLinkRepository(transactional_session)
    downstream_of_a = await repo.list_by_source(a.id)
    upstream_of_c = await repo.list_by_target(c.id)
    assert len(downstream_of_a) == 2
    assert len(upstream_of_c) == 2
```

- [ ] **Step 2: Run — verify ImportError**

```bash
PYTEST_ARGS="-v tests/repositories/test_dataset_link_repository.py" make test-docker
```

- [ ] **Step 3: Create schemas in `schemas/aide_schemas/dataset_link.py`**

```python
import uuid

from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class DatasetLinkBase(BaseModel):
    source_dataset_id: uuid.UUID
    target_dataset_id: uuid.UUID


class DatasetLinkCreate(DatasetLinkBase, NoteMixin):
    pass


class DatasetLinkUpdate(VersionedUpdateMixin, NoteMixin):
    pass


class DatasetLinkRead(DatasetLinkBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: Re-export in `backend/schemas/dataset_link.py`**

```python
from aide_schemas.dataset_link import (
    DatasetLinkCreate as DatasetLinkCreate,
    DatasetLinkRead as DatasetLinkRead,
    DatasetLinkUpdate as DatasetLinkUpdate,
)
```

- [ ] **Step 5: Create `backend/repositories/dataset_link.py`**

```python
import uuid
from typing import Sequence

from sqlalchemy import or_, select

from backend.models.dataset_link import DatasetLink
from backend.repositories.base import SoftDeleteRepository


class DatasetLinkRepository(SoftDeleteRepository[DatasetLink]):
    model = DatasetLink

    async def get_active_between(
        self, source_dataset_id: uuid.UUID, target_dataset_id: uuid.UUID
    ) -> DatasetLink | None:
        stmt = select(self.model).where(
            self.model.source_dataset_id == source_dataset_id,
            self.model.target_dataset_id == target_dataset_id,
            self.model.deleted_at.is_(None),
        )
        result = await self._execute(stmt, method="get_active_between")
        return result.scalars().first()

    async def has_active_links_for_dataset(self, dataset_id: uuid.UUID) -> bool:
        stmt = (
            select(self.model.id)
            .where(
                or_(
                    self.model.source_dataset_id == dataset_id,
                    self.model.target_dataset_id == dataset_id,
                ),
                self.model.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self._execute(stmt, method="has_active_links_for_dataset")
        return result.scalar() is not None

    async def list_by_source(self, source_dataset_id: uuid.UUID) -> Sequence[DatasetLink]:
        stmt = select(self.model).where(
            self.model.source_dataset_id == source_dataset_id,
            self.model.deleted_at.is_(None),
        )
        result = await self._execute(stmt, method="list_by_source")
        return result.scalars().all()

    async def list_by_target(self, target_dataset_id: uuid.UUID) -> Sequence[DatasetLink]:
        stmt = select(self.model).where(
            self.model.target_dataset_id == target_dataset_id,
            self.model.deleted_at.is_(None),
        )
        result = await self._execute(stmt, method="list_by_target")
        return result.scalars().all()
```

- [ ] **Step 6: Run tests**

```bash
PYTEST_ARGS="-v tests/repositories/test_dataset_link_repository.py" make test-docker
```

Expected: PASS (3 tests).

- [ ] **Step 7: Format + commit**

```bash
make format
git add schemas/aide_schemas/dataset_link.py backend/schemas/dataset_link.py \
    backend/repositories/dataset_link.py tests/repositories/test_dataset_link_repository.py
git commit -m "feat(lineage): add dataset_link schemas and repository"
```

---

## Task 6: DatasetLink service + validations

**Files:**
- Create: `backend/services/dataset_link.py`
- Create: `tests/services/test_dataset_link_service.py`

- [ ] **Step 1: Write failing service tests (mocked UoW pattern)**

Create `tests/services/test_dataset_link_service.py` using `_MockUnitOfWork` / `_MockRepository` helpers analogous to `tests/services/test_system_kind_service.py`. Include these tests:

```python
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.dataset_link import DatasetLink
from backend.models.dataset import DatasetRdbms
from backend.schemas.dataset_link import (
    DatasetLinkCreate,
    DatasetLinkRead,
)
from backend.services.dataset_link import DatasetLinkService


class _MockRepo:
    def __init__(self) -> None:
        self.get = AsyncMock()
        self.get_including_deleted = AsyncMock()
        self.get_active_between = AsyncMock(return_value=None)
        self.has_active_links_for_dataset = AsyncMock(return_value=False)
        self.list_by_source = AsyncMock(return_value=[])
        self.list_by_target = AsyncMock(return_value=[])
        self.create = AsyncMock()
        self.update = AsyncMock()
        self.delete = AsyncMock()
        self.restore = AsyncMock()
        self.get_multi_paginated = AsyncMock(return_value=([], 0))


class _MockUoW:
    def __init__(self) -> None:
        self.session = AsyncMock()
        self.datasets = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def _ds(layer: str | None, sys_id: uuid.UUID | None = None) -> DatasetRdbms:
    return DatasetRdbms(
        id=uuid.uuid4(),
        system_id=sys_id or uuid.uuid4(),
        object_name="o",
        kind="rdbms",
        schema_name="s",
        table_name="t",
        layer=layer,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        row_version=1,
    )


@pytest.fixture
def service() -> DatasetLinkService:
    return DatasetLinkService()


@pytest.mark.asyncio
class TestDatasetLinkService:
    async def test_create_happy_path(self, service: DatasetLinkService):
        src = _ds("source")
        tgt = _ds("raw")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        created = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        repo.create.return_value = created

        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=DatasetLinkCreate(
                    source_dataset_id=src.id, target_dataset_id=tgt.id
                ),
            )
        assert isinstance(result, DatasetLinkRead)
        assert result.source_dataset_id == src.id
        assert result.target_dataset_id == tgt.id

    async def test_create_self_link_rejected(self, service: DatasetLinkService):
        ds = _ds("source")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [ds, ds]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=ds.id, target_dataset_id=ds.id
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_LINK_SELF_REFERENCE

    async def test_create_source_not_found(self, service: DatasetLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        uow = _MockUoW()
        uow.datasets.get.side_effect = [None, _ds("raw")]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src_id, target_dataset_id=tgt_id
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_NOT_FOUND

    async def test_create_layer_missing(self, service: DatasetLinkService):
        src = _ds(None)
        tgt = _ds("raw")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id, target_dataset_id=tgt.id
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_LINK_LAYER_MISSING

    async def test_create_layer_order_violated(self, service: DatasetLinkService):
        src = _ds("core")
        tgt = _ds("raw")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id, target_dataset_id=tgt.id
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_LINK_LAYER_ORDER

    async def test_create_skip_layer_allowed(self, service: DatasetLinkService):
        """Source→Raw skipping CDC/Kafka must succeed."""
        src = _ds("source")
        tgt = _ds("raw")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        repo.create.return_value = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            await service.create(
                uow=uow,
                obj_in=DatasetLinkCreate(
                    source_dataset_id=src.id, target_dataset_id=tgt.id
                ),
            )

    async def test_create_cross_system_allowed(self, service: DatasetLinkService):
        sys_a, sys_b = uuid.uuid4(), uuid.uuid4()
        src = _ds("kafka", sys_a)
        tgt = _ds("raw", sys_b)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        repo.create.return_value = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            await service.create(
                uow=uow,
                obj_in=DatasetLinkCreate(
                    source_dataset_id=src.id, target_dataset_id=tgt.id
                ),
            )

    async def test_create_duplicate_active(self, service: DatasetLinkService):
        src = _ds("source")
        tgt = _ds("raw")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        repo.get_active_between.return_value = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id, target_dataset_id=tgt.id
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_LINK_ALREADY_EXISTS
```

- [ ] **Step 2: Run — verify ImportError**

```bash
PYTEST_ARGS="-v tests/services/test_dataset_link_service.py" make test-docker
```

- [ ] **Step 3: Create `backend/services/dataset_link.py`**

```python
import uuid
from typing import cast

from aide_schemas.dataset import LAYER_ORDER, DatasetLayer

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.dataset_link import DatasetLink
from backend.repositories.dataset_link import DatasetLinkRepository
from backend.schemas.dataset_link import (
    DatasetLinkCreate,
    DatasetLinkRead,
    DatasetLinkUpdate,
)
from backend.services.base import SoftDeleteService


class DatasetLinkService(
    SoftDeleteService[DatasetLink, DatasetLinkCreate, DatasetLinkUpdate, DatasetLinkRead]
):
    def __init__(self) -> None:
        super().__init__(
            model=DatasetLink,
            repository=DatasetLinkRepository,
            read_schema=DatasetLinkRead,
            not_found_error_code=errors.DATASET_LINK_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: DatasetLinkCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        if obj_in.source_dataset_id == obj_in.target_dataset_id:
            raise AppException(errors.DATASET_LINK_SELF_REFERENCE)

        source = await uow.datasets.get(obj_in.source_dataset_id)
        target = await uow.datasets.get(obj_in.target_dataset_id)
        if source is None or target is None:
            raise AppException(errors.DATASET_NOT_FOUND)

        if source.layer is None or target.layer is None:
            raise AppException(errors.DATASET_LINK_LAYER_MISSING)

        try:
            src_order = LAYER_ORDER[DatasetLayer(source.layer)]
            tgt_order = LAYER_ORDER[DatasetLayer(target.layer)]
        except (ValueError, KeyError):
            raise AppException(errors.DATASET_LINK_LAYER_MISSING)

        if tgt_order <= src_order:
            raise AppException(errors.DATASET_LINK_LAYER_ORDER)

        repo = cast(DatasetLinkRepository, self._get_repository(uow.session))
        existing = await repo.get_active_between(
            obj_in.source_dataset_id, obj_in.target_dataset_id
        )
        if existing is not None:
            raise AppException(errors.DATASET_LINK_ALREADY_EXISTS)
```

- [ ] **Step 4: Run tests**

```bash
PYTEST_ARGS="-v tests/services/test_dataset_link_service.py" make test-docker
```

Expected: PASS (8 tests).

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/services/dataset_link.py tests/services/test_dataset_link_service.py
git commit -m "feat(lineage): add dataset_link service with validations"
```

---

## Task 7: DatasetLink API + wire into app

**Files:**
- Create: `backend/api/v1/dataset_links.py`
- Modify: `backend/main.py`
- Modify: `backend/db/uow.py`
- Create: `tests/api/test_dataset_links.py`

- [ ] **Step 1: Write failing API tests**

`tests/api/test_dataset_links.py`:

```python
import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient


def _create_dataset(client: TestClient, auth_headers, system_id, name, layer):
    resp = client.post(
        "/api/v1/datasets/",
        json={
            "system_id": str(system_id),
            "object_name": name,
            "kind": "rdbms",
            "schema_name": "s",
            "table_name": name,
            "layer": layer,
        },
        headers=auth_headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_create_and_get_dataset_link(client: TestClient, admin_auth_headers, seeded_system_id):
    src_id = _create_dataset(client, admin_auth_headers, seeded_system_id, "src_l1", "source")
    tgt_id = _create_dataset(client, admin_auth_headers, seeded_system_id, "tgt_l1", "raw")

    resp = client.post(
        "/api/v1/dataset-links/",
        json={"source_dataset_id": src_id, "target_dataset_id": tgt_id},
        headers=admin_auth_headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    link_id = resp.json()["id"]

    resp2 = client.get(f"/api/v1/dataset-links/{link_id}", headers=admin_auth_headers)
    assert resp2.status_code == status.HTTP_200_OK
    assert resp2.json()["id"] == link_id


@pytest.mark.asyncio
async def test_create_dataset_link_layer_violation(client: TestClient, admin_auth_headers, seeded_system_id):
    src_id = _create_dataset(client, admin_auth_headers, seeded_system_id, "src_v", "core")
    tgt_id = _create_dataset(client, admin_auth_headers, seeded_system_id, "tgt_v", "raw")

    resp = client.post(
        "/api/v1/dataset-links/",
        json={"source_dataset_id": src_id, "target_dataset_id": tgt_id},
        headers=admin_auth_headers,
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["error_code"] == "DATASET_LINK_LAYER_ORDER"


@pytest.mark.asyncio
async def test_create_dataset_link_duplicate(client: TestClient, admin_auth_headers, seeded_system_id):
    s = _create_dataset(client, admin_auth_headers, seeded_system_id, "dup_s", "source")
    t = _create_dataset(client, admin_auth_headers, seeded_system_id, "dup_t", "raw")
    payload = {"source_dataset_id": s, "target_dataset_id": t}
    r1 = client.post("/api/v1/dataset-links/", json=payload, headers=admin_auth_headers)
    assert r1.status_code == status.HTTP_201_CREATED
    r2 = client.post("/api/v1/dataset-links/", json=payload, headers=admin_auth_headers)
    assert r2.status_code == status.HTTP_409_CONFLICT
    assert r2.json()["error_code"] == "DATASET_LINK_ALREADY_EXISTS"
```

Reuse `admin_auth_headers` and `seeded_system_id` fixtures from `tests/api/test_datasets.py`. If those fixtures aren't shared, lift them to `tests/conftest.py` or duplicate in the new file.

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/api/test_dataset_links.py" make test-docker
```

- [ ] **Step 3: Register repository in `backend/db/uow.py`**

Add to `__aenter__`:

```python
self.dataset_links = DatasetLinkRepository(self.session)
```

Add import:

```python
from backend.repositories.dataset_link import DatasetLinkRepository
```

- [ ] **Step 4: Create `backend/api/v1/dataset_links.py`**

```python
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status

from backend.api.dependencies import get_current_superuser, get_current_user
from backend.api.filter_sort import FilterSortParams, get_filter_sort_dependency
from backend.core.errors import (
    DATASET_LINK_ALREADY_EXISTS,
    DATASET_LINK_LAYER_MISSING,
    DATASET_LINK_LAYER_ORDER,
    DATASET_LINK_NOT_FOUND,
    DATASET_LINK_SELF_REFERENCE,
    DATASET_NOT_FOUND,
    ENTITY_NOT_DELETED,
    FORBIDDEN,
    UNAUTHORIZED,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.dataset_link import (
    DatasetLinkCreate,
    DatasetLinkRead,
    DatasetLinkUpdate,
)
from backend.schemas.pagination import Page
from backend.services.dataset_link import DatasetLinkService

router = APIRouter()

_filter_sort = get_filter_sort_dependency(None, (), "created_at")


@router.get("/", response_model=Page[DatasetLinkRead])
async def list_links(
    service: DatasetLinkService = Depends(DatasetLinkService),
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
    response_model=DatasetLinkRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_NOT_FOUND,
            DATASET_LINK_ALREADY_EXISTS,
            DATASET_LINK_SELF_REFERENCE,
            DATASET_LINK_LAYER_ORDER,
            DATASET_LINK_LAYER_MISSING,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def create_link(
    obj_in: DatasetLinkCreate,
    service: DatasetLinkService = Depends(DatasetLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.get(
    "/{obj_id}",
    response_model=DatasetLinkRead,
    responses={**build_error_responses(DATASET_LINK_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def get_link(
    obj_id: uuid.UUID,
    service: DatasetLinkService = Depends(DatasetLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    return await service.get_by_id(uow=uow, obj_id=obj_id)


@router.patch(
    "/{obj_id}",
    response_model=DatasetLinkRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_LINK_NOT_FOUND, VERSION_CONFLICT, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def update_link(
    obj_id: uuid.UUID,
    obj_in: DatasetLinkUpdate,
    service: DatasetLinkService = Depends(DatasetLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )


@router.delete(
    "/{obj_id}",
    response_model=DatasetLinkRead,
    dependencies=[Depends(get_current_superuser)],
    responses={**build_error_responses(DATASET_LINK_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def delete_link(
    obj_id: uuid.UUID,
    service: DatasetLinkService = Depends(DatasetLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)


@router.post(
    "/{obj_id}/restore",
    response_model=DatasetLinkRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_LINK_NOT_FOUND, ENTITY_NOT_DELETED, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def restore_link(
    obj_id: uuid.UUID,
    service: DatasetLinkService = Depends(DatasetLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.restore(uow=uow, obj_id=obj_id, restorer_id=current_user.id)
```

- [ ] **Step 5: Register router in `backend/main.py`**

Add near other v1 imports:

```python
from backend.api.v1 import dataset_links as v1_dataset_links
```

Add after the datasets router block:

```python
app.include_router(
    v1_dataset_links.router,
    prefix=f"{api_v1_prefix}/dataset-links",
    tags=["Dataset Links"],
)
```

- [ ] **Step 6: Run tests**

```bash
PYTEST_ARGS="-v tests/api/test_dataset_links.py" make test-docker
```

Expected: PASS (3 tests).

- [ ] **Step 7: Format + commit**

```bash
make format
git add backend/api/v1/dataset_links.py backend/main.py backend/db/uow.py \
    tests/api/test_dataset_links.py
git commit -m "feat(lineage): add dataset_link API"
```

---

## Task 8: FieldLink model + migration

**Files:**
- Create: `backend/models/field_link.py`
- Modify: `backend/models/__init__.py`
- Create: `backend/alembic/versions/XXXX_create_field_links.py`
- Create: `tests/models/test_field_link.py`

- [ ] **Step 1: Write failing tests in `tests/models/test_field_link.py`**

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.field import Field
from backend.models.field_link import FieldLink
from backend.models.system import System


async def _scaffold(session, sys):
    src = DatasetRdbms(system_id=sys.id, object_name="srcd", kind="rdbms", schema_name="s", table_name="srcd")
    tgt = DatasetRdbms(system_id=sys.id, object_name="tgtd", kind="rdbms", schema_name="s", table_name="tgtd")
    session.add_all([src, tgt])
    await session.flush()
    link = DatasetLink(source_dataset_id=src.id, target_dataset_id=tgt.id)
    session.add(link)
    await session.flush()
    sf = Field(dataset_id=src.id, name="col_s")
    tf = Field(dataset_id=tgt.id, name="col_t")
    session.add_all([sf, tf])
    await session.flush()
    return link, sf, tf


@pytest.mark.asyncio
async def test_field_link_create(transactional_session: AsyncSession, seeded_system: System):
    link, sf, tf = await _scaffold(transactional_session, seeded_system)
    fl = FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id)
    transactional_session.add(fl)
    await transactional_session.flush()
    await transactional_session.refresh(fl)
    assert fl.id is not None
    assert fl.row_version == 1


@pytest.mark.asyncio
async def test_field_link_target_uniqueness(transactional_session: AsyncSession, seeded_system: System):
    link, sf, tf = await _scaffold(transactional_session, seeded_system)
    sf2 = Field(dataset_id=sf.dataset_id, name="col_s2")
    transactional_session.add(sf2)
    await transactional_session.flush()
    transactional_session.add(FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id))
    await transactional_session.flush()
    transactional_session.add(FieldLink(dataset_link_id=link.id, source_field_id=sf2.id, target_field_id=tf.id))
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_field_link_source_fanout_allowed(transactional_session: AsyncSession, seeded_system: System):
    link, sf, tf = await _scaffold(transactional_session, seeded_system)
    tf2 = Field(dataset_id=tf.dataset_id, name="col_t2")
    transactional_session.add(tf2)
    await transactional_session.flush()
    transactional_session.add(FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id))
    transactional_session.add(FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf2.id))
    await transactional_session.flush()


@pytest.mark.asyncio
async def test_field_link_triple_unique(transactional_session: AsyncSession, seeded_system: System):
    link, sf, tf = await _scaffold(transactional_session, seeded_system)
    transactional_session.add(FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id))
    await transactional_session.flush()
    transactional_session.add(FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id))
    with pytest.raises(IntegrityError):
        await transactional_session.flush()


@pytest.mark.asyncio
async def test_field_link_cascade_on_dataset_link_delete(
    transactional_session: AsyncSession, seeded_system: System
):
    link, sf, tf = await _scaffold(transactional_session, seeded_system)
    fl = FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id)
    transactional_session.add(fl)
    await transactional_session.flush()

    await transactional_session.delete(link)
    await transactional_session.flush()
    remaining = (
        await transactional_session.execute(select(FieldLink))
    ).scalars().all()
    assert len(remaining) == 0
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/models/test_field_link.py" make test-docker
```

- [ ] **Step 3: Create `backend/models/field_link.py`**

```python
import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.mixins import MetaDataMixin


class FieldLink(Base, MetaDataMixin):
    __tablename__ = "field_links"

    dataset_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dataset_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    dataset_link = relationship("DatasetLink", back_populates="field_links")

    __table_args__ = (
        UniqueConstraint(
            "dataset_link_id",
            "source_field_id",
            "target_field_id",
            name="uq_field_link_triple",
        ),
        UniqueConstraint(
            "dataset_link_id",
            "target_field_id",
            name="uq_field_link_target_in_link",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"FieldLink(id={self.id}, source={self.source_field_id}, "
            f"target={self.target_field_id})"
        )
```

- [ ] **Step 4: Register in `backend/models/__init__.py`**

Add `from .field_link import FieldLink as FieldLink` and append `"FieldLink"` to `__all__`.

- [ ] **Step 5: Generate migration**

```bash
make alembic-gen
```

Strip unrelated ops. Body should look like:

```python
def upgrade() -> None:
    op.create_table(
        "field_links",
        sa.Column("dataset_link_id", sa.UUID(), nullable=False),
        sa.Column("source_field_id", sa.UUID(), nullable=False),
        sa.Column("target_field_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.ForeignKeyConstraint(["dataset_link_id"], ["dataset_links.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_link_id", "source_field_id", "target_field_id", name="uq_field_link_triple"),
        sa.UniqueConstraint("dataset_link_id", "target_field_id", name="uq_field_link_target_in_link"),
    )
    op.create_index(op.f("ix_field_links_id"), "field_links", ["id"], unique=True)
    op.create_index(op.f("ix_field_links_dataset_link_id"), "field_links", ["dataset_link_id"], unique=False)
    op.create_index(op.f("ix_field_links_source_field_id"), "field_links", ["source_field_id"], unique=False)
    op.create_index(op.f("ix_field_links_target_field_id"), "field_links", ["target_field_id"], unique=False)
    op.create_index(op.f("ix_field_links_created_by"), "field_links", ["created_by"], unique=False)
    op.create_index(op.f("ix_field_links_updated_by"), "field_links", ["updated_by"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_field_links_updated_by"), table_name="field_links")
    op.drop_index(op.f("ix_field_links_created_by"), table_name="field_links")
    op.drop_index(op.f("ix_field_links_target_field_id"), table_name="field_links")
    op.drop_index(op.f("ix_field_links_source_field_id"), table_name="field_links")
    op.drop_index(op.f("ix_field_links_dataset_link_id"), table_name="field_links")
    op.drop_index(op.f("ix_field_links_id"), table_name="field_links")
    op.drop_table("field_links")
```

- [ ] **Step 6: Run tests**

```bash
PYTEST_ARGS="-v tests/models/test_field_link.py" make test-docker
```

Expected: PASS (5 tests).

- [ ] **Step 7: Format + commit**

```bash
make format
git add backend/models/field_link.py backend/models/__init__.py \
    backend/alembic/versions/ tests/models/test_field_link.py
git commit -m "feat(lineage): add field_link model"
```

---

## Task 9: FieldLink schemas + repository

**Files:**
- Create: `schemas/aide_schemas/field_link.py`
- Create: `backend/schemas/field_link.py`
- Create: `backend/repositories/field_link.py`
- Create: `tests/repositories/test_field_link_repository.py`

- [ ] **Step 1: Write failing tests**

`tests/repositories/test_field_link_repository.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.field import Field
from backend.models.field_link import FieldLink
from backend.models.system import System
from backend.repositories.field_link import FieldLinkRepository


async def _scaffold(session, sys):
    src = DatasetRdbms(system_id=sys.id, object_name="s_fl", kind="rdbms", schema_name="s", table_name="s_fl")
    tgt = DatasetRdbms(system_id=sys.id, object_name="t_fl", kind="rdbms", schema_name="s", table_name="t_fl")
    session.add_all([src, tgt])
    await session.flush()
    link = DatasetLink(source_dataset_id=src.id, target_dataset_id=tgt.id)
    session.add(link)
    await session.flush()
    return src, tgt, link


@pytest.mark.asyncio
async def test_list_by_dataset_link(transactional_session: AsyncSession, seeded_system: System):
    src, tgt, link = await _scaffold(transactional_session, seeded_system)
    sf = Field(dataset_id=src.id, name="c1")
    tf = Field(dataset_id=tgt.id, name="c1")
    transactional_session.add_all([sf, tf])
    await transactional_session.flush()
    fl = FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id)
    transactional_session.add(fl)
    await transactional_session.flush()

    repo = FieldLinkRepository(transactional_session)
    items = await repo.list_by_dataset_link(link.id)
    assert len(items) == 1 and items[0].id == fl.id


@pytest.mark.asyncio
async def test_get_by_target_in_link(transactional_session: AsyncSession, seeded_system: System):
    src, tgt, link = await _scaffold(transactional_session, seeded_system)
    sf = Field(dataset_id=src.id, name="c2")
    tf = Field(dataset_id=tgt.id, name="c2")
    transactional_session.add_all([sf, tf])
    await transactional_session.flush()

    repo = FieldLinkRepository(transactional_session)
    assert await repo.get_by_target_in_link(link.id, tf.id) is None

    fl = FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id)
    transactional_session.add(fl)
    await transactional_session.flush()
    assert (await repo.get_by_target_in_link(link.id, tf.id)).id == fl.id


@pytest.mark.asyncio
async def test_list_by_target_field(transactional_session: AsyncSession, seeded_system: System):
    src, tgt, link = await _scaffold(transactional_session, seeded_system)
    sf = Field(dataset_id=src.id, name="c3")
    tf = Field(dataset_id=tgt.id, name="c3")
    transactional_session.add_all([sf, tf])
    await transactional_session.flush()

    repo = FieldLinkRepository(transactional_session)
    assert await repo.list_by_target_field(tf.id) == []
    fl = FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=tf.id)
    transactional_session.add(fl)
    await transactional_session.flush()
    items = await repo.list_by_target_field(tf.id)
    assert len(items) == 1 and items[0].id == fl.id


@pytest.mark.asyncio
async def test_unmapped_non_tech_fields(transactional_session: AsyncSession, seeded_system: System):
    src, tgt, link = await _scaffold(transactional_session, seeded_system)
    sf = Field(dataset_id=src.id, name="c4")
    mapped_tf = Field(dataset_id=tgt.id, name="c4")
    unmapped_tf = Field(dataset_id=tgt.id, name="c5")
    tech_tf = Field(dataset_id=tgt.id, name="etl_ts", is_tech=True)
    transactional_session.add_all([sf, mapped_tf, unmapped_tf, tech_tf])
    await transactional_session.flush()
    fl = FieldLink(dataset_link_id=link.id, source_field_id=sf.id, target_field_id=mapped_tf.id)
    transactional_session.add(fl)
    await transactional_session.flush()

    repo = FieldLinkRepository(transactional_session)
    orphans = await repo.unmapped_non_tech_fields(tgt.id)
    orphan_ids = {f.id for f in orphans}
    assert unmapped_tf.id in orphan_ids
    assert mapped_tf.id not in orphan_ids
    assert tech_tf.id not in orphan_ids
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/repositories/test_field_link_repository.py" make test-docker
```

- [ ] **Step 3: Create schemas in `schemas/aide_schemas/field_link.py`**

```python
import uuid

from pydantic import BaseModel, ConfigDict

from aide_schemas.mixins import MetaDataMixin, NoteMixin, VersionedUpdateMixin


class FieldLinkBase(BaseModel):
    dataset_link_id: uuid.UUID
    source_field_id: uuid.UUID
    target_field_id: uuid.UUID


class FieldLinkCreate(FieldLinkBase, NoteMixin):
    pass


class FieldLinkUpdate(VersionedUpdateMixin, NoteMixin):
    pass


class FieldLinkRead(FieldLinkBase, MetaDataMixin):
    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: Re-export in `backend/schemas/field_link.py`**

```python
from aide_schemas.field_link import (
    FieldLinkCreate as FieldLinkCreate,
    FieldLinkRead as FieldLinkRead,
    FieldLinkUpdate as FieldLinkUpdate,
)
```

- [ ] **Step 5: Create `backend/repositories/field_link.py`**

```python
import uuid
from typing import Sequence

from sqlalchemy import exists, select

from backend.models.field import Field
from backend.models.field_link import FieldLink
from backend.repositories.base import BaseRepository


class FieldLinkRepository(BaseRepository[FieldLink]):
    model = FieldLink

    async def list_by_dataset_link(
        self, dataset_link_id: uuid.UUID
    ) -> Sequence[FieldLink]:
        stmt = select(self.model).where(
            self.model.dataset_link_id == dataset_link_id
        )
        result = await self._execute(stmt, method="list_by_dataset_link")
        return result.scalars().all()

    async def get_by_target_in_link(
        self, dataset_link_id: uuid.UUID, target_field_id: uuid.UUID
    ) -> FieldLink | None:
        stmt = select(self.model).where(
            self.model.dataset_link_id == dataset_link_id,
            self.model.target_field_id == target_field_id,
        )
        result = await self._execute(stmt, method="get_by_target_in_link")
        return result.scalars().first()

    async def list_by_target_field(
        self, target_field_id: uuid.UUID
    ) -> Sequence[FieldLink]:
        stmt = select(self.model).where(self.model.target_field_id == target_field_id)
        result = await self._execute(stmt, method="list_by_target_field")
        return result.scalars().all()

    async def count_by_target_field(self, target_field_id: uuid.UUID) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(self.model).where(
            self.model.target_field_id == target_field_id
        )
        result = await self._execute(stmt, method="count_by_target_field")
        return int(result.scalar_one())

    async def unmapped_non_tech_fields(
        self, target_dataset_id: uuid.UUID
    ) -> Sequence[Field]:
        """Fields in the given dataset with is_tech=False and no inbound FieldLink."""
        has_link = select(self.model.id).where(
            self.model.target_field_id == Field.id
        ).exists()
        stmt = select(Field).where(
            Field.dataset_id == target_dataset_id,
            Field.is_tech.is_(False),
            ~has_link,
        )
        result = await self._execute(stmt, method="unmapped_non_tech_fields")
        return result.scalars().all()
```

- [ ] **Step 6: Run tests**

```bash
PYTEST_ARGS="-v tests/repositories/test_field_link_repository.py" make test-docker
```

Expected: PASS (4 tests).

- [ ] **Step 7: Format + commit**

```bash
make format
git add schemas/aide_schemas/field_link.py backend/schemas/field_link.py \
    backend/repositories/field_link.py tests/repositories/test_field_link_repository.py
git commit -m "feat(lineage): add field_link schemas and repository"
```

---

## Task 10: FieldLink service + validations

**Files:**
- Create: `backend/services/field_link.py`
- Create: `tests/services/test_field_link_service.py`

- [ ] **Step 1: Write failing service tests (mocked UoW)**

`tests/services/test_field_link_service.py`:

```python
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.dataset_link import DatasetLink
from backend.models.field import Field
from backend.models.field_link import FieldLink
from backend.schemas.field_link import FieldLinkCreate, FieldLinkRead
from backend.services.field_link import FieldLinkService


class _MockRepo:
    def __init__(self) -> None:
        self.get = AsyncMock()
        self.get_by_target_in_link = AsyncMock(return_value=None)
        self.count_by_target_field = AsyncMock(return_value=0)
        self.list_by_dataset_link = AsyncMock(return_value=[])
        self.list_by_target_field = AsyncMock(return_value=[])
        self.unmapped_non_tech_fields = AsyncMock(return_value=[])
        self.create = AsyncMock()
        self.update = AsyncMock()
        self.delete = AsyncMock()
        self.get_multi_paginated = AsyncMock(return_value=([], 0))


class _MockUoW:
    def __init__(self) -> None:
        self.session = AsyncMock()
        self.dataset_links = AsyncMock()
        self.fields = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _field(dataset_id: uuid.UUID, is_tech: bool = False) -> Field:
    return Field(
        id=uuid.uuid4(),
        dataset_id=dataset_id,
        name="c",
        is_tech=is_tech,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        row_version=1,
    )


def _link(src: uuid.UUID, tgt: uuid.UUID) -> DatasetLink:
    return DatasetLink(
        id=uuid.uuid4(),
        source_dataset_id=src,
        target_dataset_id=tgt,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        row_version=1,
    )


@pytest.fixture
def service() -> FieldLinkService:
    return FieldLinkService()


@pytest.mark.asyncio
class TestFieldLinkService:
    async def test_create_happy(self, service: FieldLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf, tf = _field(src_id), _field(tgt_id)
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        repo = _MockRepo()
        repo.create.return_value = FieldLink(
            id=uuid.uuid4(),
            dataset_link_id=link.id,
            source_field_id=sf.id,
            target_field_id=tf.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=FieldLinkCreate(
                    dataset_link_id=link.id,
                    source_field_id=sf.id,
                    target_field_id=tf.id,
                ),
            )
        assert isinstance(result, FieldLinkRead)

    async def test_create_rejects_wrong_source_dataset(self, service: FieldLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf = _field(uuid.uuid4())  # wrong dataset
        tf = _field(tgt_id)
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=FieldLinkCreate(
                        dataset_link_id=link.id,
                        source_field_id=sf.id,
                        target_field_id=tf.id,
                    ),
                )
        assert exc.value.error_code == errors.FIELD_LINK_SOURCE_DATASET_MISMATCH

    async def test_create_rejects_wrong_target_dataset(self, service: FieldLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf = _field(src_id)
        tf = _field(uuid.uuid4())  # wrong dataset
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=FieldLinkCreate(
                        dataset_link_id=link.id,
                        source_field_id=sf.id,
                        target_field_id=tf.id,
                    ),
                )
        assert exc.value.error_code == errors.FIELD_LINK_TARGET_DATASET_MISMATCH

    async def test_create_rejects_target_occupied(self, service: FieldLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf, tf = _field(src_id), _field(tgt_id)
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        repo = _MockRepo()
        repo.get_by_target_in_link.return_value = FieldLink(id=uuid.uuid4())
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=FieldLinkCreate(
                        dataset_link_id=link.id,
                        source_field_id=sf.id,
                        target_field_id=tf.id,
                    ),
                )
        assert exc.value.error_code == errors.FIELD_LINK_TARGET_OCCUPIED

    async def test_delete_last_link_to_non_tech_blocked(self, service: FieldLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        tf = _field(tgt_id, is_tech=False)
        fl = FieldLink(
            id=uuid.uuid4(),
            dataset_link_id=uuid.uuid4(),
            source_field_id=uuid.uuid4(),
            target_field_id=tf.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        uow = _MockUoW()
        uow.fields.get.return_value = tf
        repo = _MockRepo()
        repo.get.return_value = fl
        repo.count_by_target_field.return_value = 1  # this is the last one
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.delete(uow=uow, obj_id=fl.id)
        assert exc.value.error_code == errors.FIELD_NON_TECH_REQUIRES_SOURCE
        repo.delete.assert_not_awaited()

    async def test_delete_last_link_to_tech_ok(self, service: FieldLinkService):
        tgt_id = uuid.uuid4()
        tf = _field(tgt_id, is_tech=True)
        fl = FieldLink(
            id=uuid.uuid4(),
            dataset_link_id=uuid.uuid4(),
            source_field_id=uuid.uuid4(),
            target_field_id=tf.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        uow = _MockUoW()
        uow.fields.get.return_value = tf
        repo = _MockRepo()
        repo.get.return_value = fl
        repo.delete.return_value = fl
        repo.count_by_target_field.return_value = 1
        with patch.object(service, "_get_repository", return_value=repo):
            await service.delete(uow=uow, obj_id=fl.id)
        repo.delete.assert_awaited_once()
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/services/test_field_link_service.py" make test-docker
```

- [ ] **Step 3: Create `backend/services/field_link.py`**

```python
import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.field_link import FieldLink
from backend.repositories.field_link import FieldLinkRepository
from backend.schemas.field_link import (
    FieldLinkCreate,
    FieldLinkRead,
    FieldLinkUpdate,
)
from backend.services.base import GenericService


class FieldLinkService(
    GenericService[FieldLink, FieldLinkCreate, FieldLinkUpdate, FieldLinkRead]
):
    def __init__(self) -> None:
        super().__init__(
            model=FieldLink,
            repository=FieldLinkRepository,
            read_schema=FieldLinkRead,
            not_found_error_code=errors.FIELD_LINK_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: FieldLinkCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        link = await uow.dataset_links.get(obj_in.dataset_link_id)
        if link is None:
            raise AppException(errors.DATASET_LINK_NOT_FOUND)

        source_field = await uow.fields.get(obj_in.source_field_id)
        target_field = await uow.fields.get(obj_in.target_field_id)
        if source_field is None or target_field is None:
            raise AppException(errors.FIELD_NOT_FOUND)

        if source_field.dataset_id != link.source_dataset_id:
            raise AppException(errors.FIELD_LINK_SOURCE_DATASET_MISMATCH)
        if target_field.dataset_id != link.target_dataset_id:
            raise AppException(errors.FIELD_LINK_TARGET_DATASET_MISMATCH)

        repo = cast(FieldLinkRepository, self._get_repository(uow.session))
        if await repo.get_by_target_in_link(link.id, target_field.id):
            raise AppException(errors.FIELD_LINK_TARGET_OCCUPIED)

    async def delete(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        deleter_id: uuid.UUID | None = None,
    ) -> FieldLinkRead:
        async with uow:
            repo = cast(FieldLinkRepository, self._get_repository(uow.session))
            db_obj = await repo.get(obj_id)
            if db_obj is None:
                raise AppException(errors.FIELD_LINK_NOT_FOUND)

            target_field = await uow.fields.get(db_obj.target_field_id)
            if (
                target_field is not None
                and not target_field.is_tech
                and await repo.count_by_target_field(db_obj.target_field_id) == 1
            ):
                raise AppException(errors.FIELD_NON_TECH_REQUIRES_SOURCE)

            deleted = await repo.delete(db_obj=db_obj)
            return self.read_schema.model_validate(deleted)
```

- [ ] **Step 4: Run tests**

```bash
PYTEST_ARGS="-v tests/services/test_field_link_service.py" make test-docker
```

Expected: PASS (6 tests).

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/services/field_link.py tests/services/test_field_link_service.py
git commit -m "feat(lineage): add field_link service with validations"
```

---

## Task 11: FieldLink API + wire

**Files:**
- Create: `backend/api/v1/field_links.py`
- Modify: `backend/main.py`
- Modify: `backend/db/uow.py`
- Create: `tests/api/test_field_links.py`

- [ ] **Step 1: Write failing API tests**

`tests/api/test_field_links.py`:

```python
import pytest
from fastapi import status
from fastapi.testclient import TestClient


def _create_dataset(client, headers, system_id, name, layer):
    r = client.post(
        "/api/v1/datasets/",
        json={
            "system_id": str(system_id),
            "object_name": name,
            "kind": "rdbms",
            "schema_name": "s",
            "table_name": name,
            "layer": layer,
        },
        headers=headers,
    )
    assert r.status_code == status.HTTP_201_CREATED, r.text
    return r.json()["id"]


def _create_field(client, headers, dataset_id, name, is_tech=False):
    r = client.post(
        "/api/v1/fields/",
        json={"dataset_id": dataset_id, "name": name, "is_tech": is_tech},
        headers=headers,
    )
    assert r.status_code == status.HTTP_201_CREATED, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_create_field_link_happy(client: TestClient, admin_auth_headers, seeded_system_id):
    src = _create_dataset(client, admin_auth_headers, seeded_system_id, "fl_src", "source")
    tgt = _create_dataset(client, admin_auth_headers, seeded_system_id, "fl_tgt", "raw")
    sf = _create_field(client, admin_auth_headers, src, "c")
    tf = _create_field(client, admin_auth_headers, tgt, "c")
    link = client.post(
        "/api/v1/dataset-links/",
        json={"source_dataset_id": src, "target_dataset_id": tgt},
        headers=admin_auth_headers,
    ).json()["id"]

    resp = client.post(
        f"/api/v1/dataset-links/{link}/field-links/",
        json={
            "dataset_link_id": link,
            "source_field_id": sf,
            "target_field_id": tf,
        },
        headers=admin_auth_headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


@pytest.mark.asyncio
async def test_create_field_link_wrong_target_dataset(
    client: TestClient, admin_auth_headers, seeded_system_id
):
    src = _create_dataset(client, admin_auth_headers, seeded_system_id, "wt_src", "source")
    tgt = _create_dataset(client, admin_auth_headers, seeded_system_id, "wt_tgt", "raw")
    other = _create_dataset(client, admin_auth_headers, seeded_system_id, "wt_oth", "raw")
    sf = _create_field(client, admin_auth_headers, src, "c")
    tf_wrong = _create_field(client, admin_auth_headers, other, "c")
    link = client.post(
        "/api/v1/dataset-links/",
        json={"source_dataset_id": src, "target_dataset_id": tgt},
        headers=admin_auth_headers,
    ).json()["id"]

    resp = client.post(
        f"/api/v1/dataset-links/{link}/field-links/",
        json={
            "dataset_link_id": link,
            "source_field_id": sf,
            "target_field_id": tf_wrong,
        },
        headers=admin_auth_headers,
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["error_code"] == "FIELD_LINK_TARGET_DATASET_MISMATCH"
```

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/api/test_field_links.py" make test-docker
```

- [ ] **Step 3: Register repo in `backend/db/uow.py`**

Add import:

```python
from backend.repositories.field_link import FieldLinkRepository
```

Add in `__aenter__`:

```python
self.field_links = FieldLinkRepository(self.session)
```

- [ ] **Step 4: Create `backend/api/v1/field_links.py`**

```python
import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_current_superuser, get_current_user
from backend.core.errors import (
    DATASET_LINK_NOT_FOUND,
    FIELD_LINK_ALREADY_EXISTS,
    FIELD_LINK_NOT_FOUND,
    FIELD_LINK_SOURCE_DATASET_MISMATCH,
    FIELD_LINK_TARGET_DATASET_MISMATCH,
    FIELD_LINK_TARGET_OCCUPIED,
    FIELD_NON_TECH_REQUIRES_SOURCE,
    FIELD_NOT_FOUND,
    FORBIDDEN,
    UNAUTHORIZED,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.field_link import (
    FieldLinkCreate,
    FieldLinkRead,
    FieldLinkUpdate,
)
from backend.services.field_link import FieldLinkService

router = APIRouter()


@router.get(
    "/dataset-links/{dataset_link_id}/field-links/",
    response_model=list[FieldLinkRead],
    responses={**build_error_responses(UNAUTHORIZED, FORBIDDEN)},
)
async def list_by_dataset_link(
    dataset_link_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    async with uow:
        items = await uow.field_links.list_by_dataset_link(dataset_link_id)
        return [FieldLinkRead.model_validate(it) for it in items]


@router.post(
    "/dataset-links/{dataset_link_id}/field-links/",
    response_model=FieldLinkRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_LINK_NOT_FOUND,
            FIELD_NOT_FOUND,
            FIELD_LINK_ALREADY_EXISTS,
            FIELD_LINK_SOURCE_DATASET_MISMATCH,
            FIELD_LINK_TARGET_DATASET_MISMATCH,
            FIELD_LINK_TARGET_OCCUPIED,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def create_field_link(
    dataset_link_id: uuid.UUID,
    obj_in: FieldLinkCreate,
    service: FieldLinkService = Depends(FieldLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    # Path and body must agree on dataset_link_id
    obj_in = obj_in.model_copy(update={"dataset_link_id": dataset_link_id})
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.patch(
    "/field-links/{obj_id}",
    response_model=FieldLinkRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            FIELD_LINK_NOT_FOUND, VERSION_CONFLICT, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def update_field_link(
    obj_id: uuid.UUID,
    obj_in: FieldLinkUpdate,
    service: FieldLinkService = Depends(FieldLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )


@router.delete(
    "/field-links/{obj_id}",
    response_model=FieldLinkRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            FIELD_LINK_NOT_FOUND,
            FIELD_NON_TECH_REQUIRES_SOURCE,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def delete_field_link(
    obj_id: uuid.UUID,
    service: FieldLinkService = Depends(FieldLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)
```

- [ ] **Step 5: Register router in `backend/main.py`**

```python
from backend.api.v1 import field_links as v1_field_links
```

```python
app.include_router(
    v1_field_links.router,
    prefix=f"{api_v1_prefix}",
    tags=["Field Links"],
)
```

Note: this router's paths already include the full `/dataset-links/{id}/field-links/` prefix, so the included prefix is just `/api/v1`.

- [ ] **Step 6: Run tests**

```bash
PYTEST_ARGS="-v tests/api/test_field_links.py" make test-docker
```

Expected: PASS (2 tests).

- [ ] **Step 7: Format + commit**

```bash
make format
git add backend/api/v1/field_links.py backend/main.py backend/db/uow.py \
    tests/api/test_field_links.py
git commit -m "feat(lineage): add field_link API"
```

- [ ] **Step 8: Add bulk-create endpoint (spec §5.1/5.2)**

Append to `tests/api/test_field_links.py`:

```python
@pytest.mark.asyncio
async def test_bulk_create_field_links(client, admin_auth_headers, seeded_system_id):
    src = _create_dataset(client, admin_auth_headers, seeded_system_id, "bk_s", "source")
    tgt = _create_dataset(client, admin_auth_headers, seeded_system_id, "bk_t", "raw")
    sf1 = _create_field(client, admin_auth_headers, src, "a")
    sf2 = _create_field(client, admin_auth_headers, src, "b")
    tf1 = _create_field(client, admin_auth_headers, tgt, "a")
    tf2 = _create_field(client, admin_auth_headers, tgt, "b")
    link = client.post(
        "/api/v1/dataset-links/",
        json={"source_dataset_id": src, "target_dataset_id": tgt},
        headers=admin_auth_headers,
    ).json()["id"]

    resp = client.post(
        f"/api/v1/dataset-links/{link}/field-links/bulk",
        json=[
            {"dataset_link_id": link, "source_field_id": sf1, "target_field_id": tf1},
            {"dataset_link_id": link, "source_field_id": sf2, "target_field_id": tf2},
        ],
        headers=admin_auth_headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    assert len(resp.json()) == 2
```

Add to `backend/services/field_link.py`:

```python
async def bulk_create(
    self,
    uow: UnitOfWork,
    items: list[FieldLinkCreate],
    creator_id: uuid.UUID | None = None,
) -> list[FieldLinkRead]:
    """Create many field_links in one transaction (all-or-nothing)."""
    if not items:
        return []
    async with uow:
        for it in items:
            await self._pre_create(uow, it, creator_id)
        repo = cast(FieldLinkRepository, self._get_repository(uow.session))
        db_objs: list[FieldLink] = []
        for it in items:
            obj = FieldLink(**it.model_dump())
            if creator_id:
                obj.created_by = creator_id
                obj.updated_by = creator_id
            db_objs.append(obj)
        created = await repo.create_many(objs=db_objs)
        return [self.read_schema.model_validate(o) for o in created]
```

Add to `backend/api/v1/field_links.py`:

```python
@router.post(
    "/dataset-links/{dataset_link_id}/field-links/bulk",
    response_model=list[FieldLinkRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_LINK_NOT_FOUND,
            FIELD_NOT_FOUND,
            FIELD_LINK_ALREADY_EXISTS,
            FIELD_LINK_SOURCE_DATASET_MISMATCH,
            FIELD_LINK_TARGET_DATASET_MISMATCH,
            FIELD_LINK_TARGET_OCCUPIED,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def bulk_create_field_links(
    dataset_link_id: uuid.UUID,
    items: list[FieldLinkCreate],
    service: FieldLinkService = Depends(FieldLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    items = [it.model_copy(update={"dataset_link_id": dataset_link_id}) for it in items]
    return await service.bulk_create(uow=uow, items=items, creator_id=current_user.id)
```

Run tests:

```bash
PYTEST_ARGS="-v tests/api/test_field_links.py::test_bulk_create_field_links" make test-docker
```

Expected: PASS.

Format + commit:

```bash
make format
git add backend/services/field_link.py backend/api/v1/field_links.py tests/api/test_field_links.py
git commit -m "feat(lineage): add field_link bulk-create endpoint"
```

---

## Task 12: Extend DatasetService — block delete on active links

**Files:**
- Modify: `backend/services/dataset.py`
- Modify: `tests/services/test_dataset_service.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/services/test_dataset_service.py` (it uses the mocked UoW pattern — inspect existing tests for the exact shape of mocks used):

```python
@pytest.mark.asyncio
async def test_delete_blocked_when_has_active_dataset_links(
    dataset_service: DatasetService, mock_uow, db_dataset_rdbms: DatasetRdbms
):
    mock_uow.dataset_links = AsyncMock()
    mock_uow.dataset_links.has_active_links_for_dataset = AsyncMock(return_value=True)
    mock_repo = _MockDatasetRepo()
    mock_repo.get.return_value = db_dataset_rdbms
    with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
        with pytest.raises(AppException) as exc:
            await dataset_service.delete(uow=mock_uow, obj_id=db_dataset_rdbms.id)
    assert exc.value.error_code == errors.DATASET_HAS_ACTIVE_LINKS
    mock_repo.delete.assert_not_awaited()
```

If `mock_uow` does not expose `dataset_links` in the existing fixture, add it there. `_MockDatasetRepo` must include `delete: AsyncMock`.

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/services/test_dataset_service.py::test_delete_blocked_when_has_active_dataset_links" make test-docker
```

- [ ] **Step 3: Override `_pre_delete` in `backend/services/dataset.py`**

Add this method inside `DatasetService`:

```python
async def _pre_delete(self, uow: UnitOfWork, db_obj: Dataset) -> None:
    if await uow.dataset_links.has_active_links_for_dataset(db_obj.id):
        raise AppException(errors.DATASET_HAS_ACTIVE_LINKS)
```

Keep existing `_pre_delete` logic if any — merge the new check.

- [ ] **Step 4: Run tests**

```bash
PYTEST_ARGS="-v tests/services/test_dataset_service.py" make test-docker
```

Expected: PASS.

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/services/dataset.py tests/services/test_dataset_service.py
git commit -m "feat(dataset): block delete when lineage links exist"
```

---

## Task 13: Extend FieldService — is_tech=False requires inbound links

**Files:**
- Modify: `backend/services/field.py`
- Modify: `tests/services/test_field_service.py` (may need to create if it doesn't exist)

- [ ] **Step 1: Write the failing test**

Add to the existing field service test file (create `tests/services/test_field_service.py` if missing):

```python
@pytest.mark.asyncio
async def test_update_to_non_tech_requires_inbound_links(
    field_service: FieldService, mock_uow, db_field: Field
):
    # db_field currently is_tech=True; update to is_tech=False with no inbound links → reject
    db_field.is_tech = True
    mock_uow.field_links = AsyncMock()
    mock_uow.field_links.count_by_target_field = AsyncMock(return_value=0)
    mock_repo = _MockFieldRepo()
    mock_repo.get.return_value = db_field
    mock_repo.get_by_dataset_and_name.return_value = None
    update = FieldUpdate(is_tech=False, row_version=db_field.row_version)
    with patch.object(field_service, "_get_repository", return_value=mock_repo):
        with pytest.raises(AppException) as exc:
            await field_service.update(
                uow=mock_uow, obj_id=db_field.id, obj_in=update
            )
    assert exc.value.error_code == errors.FIELD_NON_TECH_REQUIRES_SOURCE


@pytest.mark.asyncio
async def test_update_to_non_tech_allowed_when_has_links(
    field_service: FieldService, mock_uow, db_field: Field
):
    db_field.is_tech = True
    mock_uow.field_links = AsyncMock()
    mock_uow.field_links.count_by_target_field = AsyncMock(return_value=1)
    mock_repo = _MockFieldRepo()
    mock_repo.get.return_value = db_field
    mock_repo.get_by_dataset_and_name.return_value = None
    mock_repo.update.return_value = db_field
    update = FieldUpdate(is_tech=False, row_version=db_field.row_version)
    with patch.object(field_service, "_get_repository", return_value=mock_repo):
        await field_service.update(uow=mock_uow, obj_id=db_field.id, obj_in=update)
```

Add `_MockFieldRepo` and `db_field` fixture matching the shape used in `_MockRepository` / `db_system_kind` in `tests/services/test_system_kind_service.py`. Required mock methods: `get, get_by_dataset_and_name, create, update, delete, get_multi_paginated`.

- [ ] **Step 2: Run — FAIL**

```bash
PYTEST_ARGS="-v tests/services/test_field_service.py" make test-docker
```

- [ ] **Step 3: Extend `_pre_update` in `backend/services/field.py`**

Inside `FieldService._pre_update`, before the uniqueness block, add:

```python
new_is_tech = update_data.get("is_tech", db_obj.is_tech)
if new_is_tech is False and db_obj.is_tech is True:
    if await uow.field_links.count_by_target_field(db_obj.id) == 0:
        raise AppException(errors.FIELD_NON_TECH_REQUIRES_SOURCE)
```

- [ ] **Step 4: Run tests**

```bash
PYTEST_ARGS="-v tests/services/test_field_service.py" make test-docker
```

Expected: PASS.

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/services/field.py tests/services/test_field_service.py
git commit -m "feat(field): validate is_tech toggle against field_links"
```

---

## Task 14: Datasets API — upstream/downstream/unmapped endpoints

**Files:**
- Modify: `backend/api/v1/datasets.py`
- Modify: `tests/api/test_datasets.py`

- [ ] **Step 1: Write failing API tests**

Add to `tests/api/test_datasets.py`:

```python
@pytest.mark.asyncio
async def test_upstream_downstream_links(client, admin_auth_headers, seeded_system_id):
    a = _create_dataset(client, admin_auth_headers, seeded_system_id, "ud_a", "source")
    b = _create_dataset(client, admin_auth_headers, seeded_system_id, "ud_b", "raw")
    c = _create_dataset(client, admin_auth_headers, seeded_system_id, "ud_c", "core")
    client.post("/api/v1/dataset-links/", json={"source_dataset_id": a, "target_dataset_id": b}, headers=admin_auth_headers)
    client.post("/api/v1/dataset-links/", json={"source_dataset_id": b, "target_dataset_id": c}, headers=admin_auth_headers)

    up = client.get(f"/api/v1/datasets/{b}/upstream-links", headers=admin_auth_headers)
    down = client.get(f"/api/v1/datasets/{b}/downstream-links", headers=admin_auth_headers)
    assert up.status_code == 200 and len(up.json()) == 1
    assert down.status_code == 200 and len(down.json()) == 1


@pytest.mark.asyncio
async def test_unmapped_fields(client, admin_auth_headers, seeded_system_id):
    src = _create_dataset(client, admin_auth_headers, seeded_system_id, "um_s", "source")
    tgt = _create_dataset(client, admin_auth_headers, seeded_system_id, "um_t", "raw")
    # Target dataset with two non-tech fields and one tech field
    f1 = _create_field(client, admin_auth_headers, tgt, "a")
    _create_field(client, admin_auth_headers, tgt, "b")
    _create_field(client, admin_auth_headers, tgt, "etl_ts", is_tech=True)
    sf = _create_field(client, admin_auth_headers, src, "a")
    link_id = client.post(
        "/api/v1/dataset-links/",
        json={"source_dataset_id": src, "target_dataset_id": tgt},
        headers=admin_auth_headers,
    ).json()["id"]
    client.post(
        f"/api/v1/dataset-links/{link_id}/field-links/",
        json={"dataset_link_id": link_id, "source_field_id": sf, "target_field_id": f1},
        headers=admin_auth_headers,
    )

    resp = client.get(f"/api/v1/datasets/{tgt}/unmapped-fields", headers=admin_auth_headers)
    assert resp.status_code == 200
    names = {f["name"] for f in resp.json()}
    assert names == {"b"}
```

Helpers `_create_dataset`, `_create_field` may be imported from the field_links test file or duplicated — prefer moving to `tests/conftest.py` if you touch them twice.

- [ ] **Step 2: Run — FAIL (404 for endpoint)**

```bash
PYTEST_ARGS="-v tests/api/test_datasets.py::test_upstream_downstream_links tests/api/test_datasets.py::test_unmapped_fields" make test-docker
```

- [ ] **Step 3: Add endpoints to `backend/api/v1/datasets.py`**

Append after the existing `restore` endpoint:

```python
from backend.schemas.dataset_link import DatasetLinkRead
from backend.schemas.field import FieldRead


@router.get(
    "/{obj_id}/upstream-links",
    response_model=list[DatasetLinkRead],
    summary="List dataset links where this dataset is the target",
    responses={**build_error_responses(DATASET_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def get_upstream_links(
    obj_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    async with uow:
        if not await uow.datasets.get(obj_id):
            from backend.core.exceptions import AppException
            raise AppException(DATASET_NOT_FOUND)
        items = await uow.dataset_links.list_by_target(obj_id)
        return [DatasetLinkRead.model_validate(i) for i in items]


@router.get(
    "/{obj_id}/downstream-links",
    response_model=list[DatasetLinkRead],
    summary="List dataset links where this dataset is the source",
    responses={**build_error_responses(DATASET_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def get_downstream_links(
    obj_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    async with uow:
        if not await uow.datasets.get(obj_id):
            from backend.core.exceptions import AppException
            raise AppException(DATASET_NOT_FOUND)
        items = await uow.dataset_links.list_by_source(obj_id)
        return [DatasetLinkRead.model_validate(i) for i in items]


@router.get(
    "/{obj_id}/unmapped-fields",
    response_model=list[FieldRead],
    summary="Non-technical fields of this dataset with no inbound field_link",
    responses={**build_error_responses(DATASET_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def get_unmapped_fields(
    obj_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    async with uow:
        if not await uow.datasets.get(obj_id):
            from backend.core.exceptions import AppException
            raise AppException(DATASET_NOT_FOUND)
        items = await uow.field_links.unmapped_non_tech_fields(obj_id)
        return [FieldRead.model_validate(i) for i in items]
```

- [ ] **Step 4: Run tests**

```bash
PYTEST_ARGS="-v tests/api/test_datasets.py" make test-docker
```

Expected: PASS (all existing + 2 new tests).

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/api/v1/datasets.py tests/api/test_datasets.py
git commit -m "feat(dataset): add upstream/downstream/unmapped endpoints"
```

---

## Task 15: Run the full test suite

**Files:** none changed — this is a verification step.

- [ ] **Step 1: Run entire suite**

```bash
make test-docker
```

Expected: all tests pass. If a failure points to an existing test whose fixtures don't yet know about `is_tech` or `layer` as an enum value, adjust the fixture. Do NOT weaken the enum or relax the `is_tech` default.

- [ ] **Step 2: Run lint + type-check**

```bash
make check
```

Fix any new issues introduced by the plan; ignore pre-existing mypy errors noted in CLAUDE.md (`backend/scripts/_seed_core.py`, `sdk/aide_sdk/resources/datasets.py`).

- [ ] **Step 3: Commit any fixes**

If fixes were needed:

```bash
git add -A
git commit -m "chore: suite cleanup for lineage feature"
```

Otherwise skip.

---

## Task 16: Update data model doc + ADR

**Files:**
- Modify: `docs/AIDE_data_model.json`
- Create: `docs/adr/adr-016-dataset-lineage.md`
- Modify: `docs/adr/README.md`

- [ ] **Step 1: Update `docs/AIDE_data_model.json`**

Add two tables — `dataset_links`, `field_links` — and two columns (`datasets.pattern_code`, `fields.is_tech`) using the ChartDB format already in use. Follow existing entries as templates. Include FK relationships:

- `dataset_links.source_dataset_id → datasets.id`
- `dataset_links.target_dataset_id → datasets.id`
- `field_links.dataset_link_id → dataset_links.id` (CASCADE)
- `field_links.source_field_id → fields.id` (CASCADE)
- `field_links.target_field_id → fields.id` (CASCADE)

- [ ] **Step 2: Create `docs/adr/adr-016-dataset-lineage.md`**

Follow the structure of `adr-008-polymorphic-dataset.md`. Title: `ADR-016: Dataset Lineage — Two-Level Link Model`. Date: 2026-04-21. Status: Accepted. Sections: Context, Options Considered, Decision, Consequences. Key decisions to document:

- Two-level (`dataset_link` + `field_link`) vs field-level-only
- Layer order validation replaces explicit DAG-cycle check
- Block dataset delete when linked vs cascade
- Detached tech-field templates (no FK on Field) — covered more in Phase 2 plan but mentioned here
- Abstract `type_code` for resolver (Phase 2)
- Target field exclusivity inside one dataset_link; source reuse allowed

Include a "Related" pointer to the spec at `docs/superpowers/specs/2026-04-21-dataset-lineage-design.md` and to Phase 2 plan (TBD filename) once created.

- [ ] **Step 3: Update `docs/adr/README.md`**

Add a row to the index table in the same style as existing rows, pointing to ADR-016.

- [ ] **Step 4: Commit**

```bash
git add docs/AIDE_data_model.json docs/adr/adr-016-dataset-lineage.md docs/adr/README.md
git commit -m "docs: add ADR-016 dataset lineage"
```

---

## Closing

All 16 tasks complete. The feature is merge-ready when:

- `make test-docker` passes full suite
- `make check` passes (ignoring documented pre-existing mypy issues)
- The five new tables/columns appear in `docs/AIDE_data_model.json`
- ADR-016 is indexed in `docs/adr/README.md`

Phase 2 (tech-field templates + `apply_tech_template` endpoint + resolver) will build on the `is_tech` column landed here and does not modify any of the Phase 1 tables. See the spec section 8 for Phase 2 scope.
