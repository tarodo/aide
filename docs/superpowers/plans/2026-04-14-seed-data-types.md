# Seed Data Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a standalone idempotent Python script that seeds the metastore with all built-in PostgreSQL 14 data types (plus the required `SystemKind` and `SystemFlavor` rows) driven by a curated YAML file.

**Architecture:** Thin CLI entry point (`seed_data_types.py`) parses args and calls a pure async orchestrator in `_seed_core.py`. Orchestrator validates YAML via Pydantic, then upserts `SystemKind` → `SystemFlavor` → `DataType` rows inside a single transaction using the existing `UnitOfWork`. Data lives in `backend/scripts/data/postgres14.yaml`, generated once via Context7 and committed. Tests run in Docker against a real Postgres via the existing transactional fixture.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 async, Pydantic v2, PyYAML, pytest + pytest-asyncio.

---

## File Structure

```
backend/scripts/
├── seed_data_types.py          # CREATE: CLI entry (argparse + asyncio.run)
├── _seed_core.py               # CREATE: Pydantic schemas + seed_from_file orchestrator
└── data/
    ├── __init__.py             # CREATE: empty marker
    └── postgres14.yaml         # CREATE: curated types (generated via Context7)

tests/scripts/
├── __init__.py                 # CREATE: empty marker
├── test_seed_schemas.py        # CREATE: Pydantic validation tests
├── test_seed_upserts.py        # CREATE: per-entity upsert tests (kind, flavor, type)
└── test_seed_runner.py         # CREATE: end-to-end orchestrator + CLI tests
```

**Responsibilities:**
- `_seed_core.py` holds all logic (models + upserts + `seed_from_file`). Pure, no argparse, no `print`. Returns a structured `SeedReport` dataclass.
- `seed_data_types.py` only: parse args, build `UnitOfWork`, call `seed_from_file`, print report.
- Tests split by concern: schema validation, per-entity upsert semantics, full orchestrator + CLI.

---

## Preliminary: add PyYAML dependency

- [ ] **Step 1: Add `pyyaml` to backend deps**

Edit `backend/pyproject.toml` dependencies section. Add `"pyyaml>=6.0"`.

- [ ] **Step 2: Sync lockfile**

Run: `uv sync`
Expected: lockfile updated, no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml uv.lock
git commit -m "deps: add pyyaml for seed scripts"
```

---

## Task 1: Pydantic seed schemas

**Files:**
- Create: `backend/scripts/__init__.py` (if absent — check first, may already exist)
- Create: `backend/scripts/_seed_core.py`
- Create: `tests/scripts/__init__.py`
- Create: `tests/scripts/test_seed_schemas.py`

- [ ] **Step 1: Write failing test for valid YAML parse**

`tests/scripts/test_seed_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from backend.scripts._seed_core import SeedFile


def test_seed_file_parses_minimal_valid_doc():
    doc = {
        "kind": {"code": "rdbms", "name": "Relational Database"},
        "flavor": {
            "code": "postgres14",
            "name": "PostgreSQL",
            "vendor": "PostgreSQL Global Development Group",
            "versions": ["14", "15"],
        },
        "types": [
            {
                "code": "bigint",
                "params_schema": {},
                "render_template": "bigint",
            },
            {
                "code": "varchar",
                "params_schema": {
                    "length": {"type": "int", "required": False, "default": None}
                },
                "render_template": "varchar({length})",
            },
        ],
    }
    parsed = SeedFile.model_validate(doc)
    assert parsed.flavor.code == "postgres14"
    assert parsed.flavor.versions == ["14", "15"]
    assert len(parsed.types) == 2
    assert parsed.types[1].params_schema["length"].type == "int"


def test_seed_file_rejects_missing_flavor_code():
    doc = {
        "kind": {"code": "rdbms", "name": "Relational Database"},
        "flavor": {"name": "PostgreSQL", "versions": ["14"]},
        "types": [],
    }
    with pytest.raises(ValidationError):
        SeedFile.model_validate(doc)


def test_seed_file_rejects_duplicate_type_codes():
    doc = {
        "kind": {"code": "rdbms", "name": "Relational Database"},
        "flavor": {"code": "postgres14", "name": "PostgreSQL", "versions": ["14"]},
        "types": [
            {"code": "bigint", "params_schema": {}, "render_template": "bigint"},
            {"code": "bigint", "params_schema": {}, "render_template": "bigint"},
        ],
    }
    with pytest.raises(ValidationError):
        SeedFile.model_validate(doc)
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd backend && uv run pytest ../tests/scripts/test_seed_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.scripts._seed_core` or `ImportError: SeedFile`.

- [ ] **Step 3: Implement schemas**

`backend/scripts/_seed_core.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


class SeedParamSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["int", "str", "bool"]
    required: bool = False
    default: Any = None


class SeedKind(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str


class SeedFlavor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    vendor: str | None = None
    versions: list[str] = []


class SeedType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    params_schema: dict[str, SeedParamSpec] = {}
    render_template: str | None = None


class SeedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SeedKind
    flavor: SeedFlavor
    types: list[SeedType]

    @field_validator("types")
    @classmethod
    def _unique_codes(cls, v: list[SeedType]) -> list[SeedType]:
        codes = [t.code for t in v]
        if len(codes) != len(set(codes)):
            dups = {c for c in codes if codes.count(c) > 1}
            raise ValueError(f"Duplicate type codes in seed file: {sorted(dups)}")
        return v
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest ../tests/scripts/test_seed_schemas.py -v`
Expected: 3 passed.

- [ ] **Step 5: Format + check**

Run: `make format && make check`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/_seed_core.py tests/scripts/
git commit -m "feat(seed): add Pydantic schemas for data types seed file"
```

---

## Task 2: YAML loader

**Files:**
- Modify: `backend/scripts/_seed_core.py` (append `load_seed_file` function)
- Modify: `tests/scripts/test_seed_schemas.py` (append YAML tests)

- [ ] **Step 1: Write failing test**

Append to `tests/scripts/test_seed_schemas.py`:

```python
import textwrap

from backend.scripts._seed_core import load_seed_file


def test_load_seed_file_parses_yaml(tmp_path):
    yaml_text = textwrap.dedent(
        """
        kind:
          code: rdbms
          name: Relational Database
        flavor:
          code: postgres14
          name: PostgreSQL
          vendor: PostgreSQL Global Development Group
          versions: ["14"]
        types:
          - code: bigint
            params_schema: {}
            render_template: bigint
        """
    )
    p = tmp_path / "seed.yaml"
    p.write_text(yaml_text)

    parsed = load_seed_file(p)
    assert parsed.flavor.code == "postgres14"
    assert parsed.types[0].code == "bigint"


def test_load_seed_file_raises_on_unknown_field(tmp_path):
    p = tmp_path / "seed.yaml"
    p.write_text(
        "kind: {code: rdbms, name: X}\n"
        "flavor: {code: c, name: n, versions: []}\n"
        "types: []\n"
        "bogus: true\n"
    )
    with pytest.raises(Exception):
        load_seed_file(p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest ../tests/scripts/test_seed_schemas.py -v -k load_seed_file`
Expected: FAIL — `ImportError: load_seed_file`.

- [ ] **Step 3: Implement loader**

Append to `backend/scripts/_seed_core.py`:

```python
from pathlib import Path

import yaml


def load_seed_file(path: Path | str) -> SeedFile:
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Seed file {path} did not parse to a mapping")
    return SeedFile.model_validate(raw)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest ../tests/scripts/test_seed_schemas.py -v`
Expected: 5 passed.

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/scripts/_seed_core.py tests/scripts/test_seed_schemas.py
git commit -m "feat(seed): add YAML loader for seed files"
```

---

## Task 3: SeedReport dataclass + SystemKind upsert

**Files:**
- Modify: `backend/scripts/_seed_core.py`
- Create: `tests/scripts/test_seed_upserts.py`

- [ ] **Step 1: Write failing test for kind upsert**

`tests/scripts/test_seed_upserts.py`:

```python
import pytest
from sqlalchemy import select

from backend.models.system_kind import SystemKind
from backend.scripts._seed_core import SeedKind, upsert_system_kind


@pytest.mark.asyncio
async def test_upsert_kind_inserts_when_missing(transactional_session):
    spec = SeedKind(code="rdbms", name="Relational Database")
    obj, status = await upsert_system_kind(transactional_session, spec)
    assert status == "inserted"
    assert obj.code == "rdbms"
    assert obj.name == "Relational Database"


@pytest.mark.asyncio
async def test_upsert_kind_noop_when_unchanged(transactional_session):
    spec = SeedKind(code="rdbms", name="Relational Database")
    await upsert_system_kind(transactional_session, spec)
    _, status = await upsert_system_kind(transactional_session, spec)
    assert status == "unchanged"


@pytest.mark.asyncio
async def test_upsert_kind_updates_when_name_changes(transactional_session):
    await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="Old")
    )
    obj, status = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="New")
    )
    assert status == "updated"
    assert obj.name == "New"


@pytest.mark.asyncio
async def test_upsert_kind_restores_soft_deleted(transactional_session):
    from datetime import datetime, timezone

    obj, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    obj.deleted_at = datetime.now(timezone.utc)
    await transactional_session.flush()

    obj2, status = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    assert status == "restored"
    assert obj2.deleted_at is None

    check = await transactional_session.execute(
        select(SystemKind).where(SystemKind.code == "rdbms")
    )
    assert len(check.scalars().all()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/scripts/test_seed_upserts.py -v`
Expected: FAIL — `ImportError: upsert_system_kind`.

Note: `transactional_session` fixture already exists in `tests/conftest.py`. Full test run must go through `make test-docker` (spec rule). For quick iteration while implementing, you still need Docker — run `make test-docker` and tail output.

- [ ] **Step 3: Implement `SeedReport` + `upsert_system_kind`**

Append to `backend/scripts/_seed_core.py`:

```python
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.system_kind import SystemKind
from backend.models.system_flavor import SystemFlavor
from backend.models.data_type import DataType

UpsertStatus = Literal["inserted", "updated", "unchanged", "restored"]


@dataclass
class SeedReport:
    kind: UpsertStatus | None = None
    flavor: UpsertStatus | None = None
    types_inserted: int = 0
    types_updated: int = 0
    types_unchanged: int = 0
    types_restored: int = 0


async def upsert_system_kind(
    session: AsyncSession, spec: SeedKind
) -> tuple[SystemKind, UpsertStatus]:
    from sqlalchemy import select

    stmt = select(SystemKind).where(SystemKind.code == spec.code)
    existing = (await session.execute(stmt)).scalars().first()

    if existing is None:
        obj = SystemKind(code=spec.code, name=spec.name)
        session.add(obj)
        await session.flush()
        return obj, "inserted"

    if existing.deleted_at is not None:
        existing.deleted_at = None
        existing.name = spec.name
        await session.flush()
        return existing, "restored"

    if existing.name != spec.name:
        existing.name = spec.name
        await session.flush()
        return existing, "updated"

    return existing, "unchanged"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-docker` (watch for `test_seed_upserts.py` results).
Expected: 4 tests pass.

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/scripts/_seed_core.py tests/scripts/test_seed_upserts.py
git commit -m "feat(seed): add SystemKind upsert + SeedReport"
```

---

## Task 4: SystemFlavor upsert

**Files:**
- Modify: `backend/scripts/_seed_core.py`
- Modify: `tests/scripts/test_seed_upserts.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/scripts/test_seed_upserts.py`:

```python
from backend.scripts._seed_core import SeedFlavor, upsert_system_flavor


@pytest.mark.asyncio
async def test_upsert_flavor_inserts_with_kind_fk(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    spec = SeedFlavor(
        code="postgres14",
        name="PostgreSQL",
        vendor="PGDG",
        versions=["14", "15"],
    )
    obj, status = await upsert_system_flavor(transactional_session, spec, kind.id)
    assert status == "inserted"
    assert obj.kind_id == kind.id
    assert obj.versions == ["14", "15"]


@pytest.mark.asyncio
async def test_upsert_flavor_updates_when_versions_change(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    await upsert_system_flavor(
        transactional_session,
        SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14"]),
        kind.id,
    )
    obj, status = await upsert_system_flavor(
        transactional_session,
        SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14", "15"]),
        kind.id,
    )
    assert status == "updated"
    assert obj.versions == ["14", "15"]


@pytest.mark.asyncio
async def test_upsert_flavor_noop_when_unchanged(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    spec = SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14"])
    await upsert_system_flavor(transactional_session, spec, kind.id)
    _, status = await upsert_system_flavor(transactional_session, spec, kind.id)
    assert status == "unchanged"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-docker`
Expected: 3 new tests FAIL — `ImportError: upsert_system_flavor`.

- [ ] **Step 3: Implement**

Append to `backend/scripts/_seed_core.py`:

```python
import uuid


async def upsert_system_flavor(
    session: AsyncSession, spec: SeedFlavor, kind_id: uuid.UUID
) -> tuple[SystemFlavor, UpsertStatus]:
    from sqlalchemy import select

    stmt = select(SystemFlavor).where(SystemFlavor.code == spec.code)
    existing = (await session.execute(stmt)).scalars().first()

    if existing is None:
        obj = SystemFlavor(
            code=spec.code,
            name=spec.name,
            vendor=spec.vendor,
            versions=list(spec.versions),
            kind_id=kind_id,
        )
        session.add(obj)
        await session.flush()
        return obj, "inserted"

    fields_changed = (
        existing.name != spec.name
        or existing.vendor != spec.vendor
        or list(existing.versions or []) != list(spec.versions)
        or existing.kind_id != kind_id
    )

    if existing.deleted_at is not None:
        existing.deleted_at = None
        existing.name = spec.name
        existing.vendor = spec.vendor
        existing.versions = list(spec.versions)
        existing.kind_id = kind_id
        await session.flush()
        return existing, "restored"

    if fields_changed:
        existing.name = spec.name
        existing.vendor = spec.vendor
        existing.versions = list(spec.versions)
        existing.kind_id = kind_id
        await session.flush()
        return existing, "updated"

    return existing, "unchanged"
```

- [ ] **Step 4: Run tests**

Run: `make test-docker`
Expected: all `test_seed_upserts.py` tests pass.

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/scripts/_seed_core.py tests/scripts/test_seed_upserts.py
git commit -m "feat(seed): add SystemFlavor upsert"
```

---

## Task 5: DataType upsert

**Files:**
- Modify: `backend/scripts/_seed_core.py`
- Modify: `tests/scripts/test_seed_upserts.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/scripts/test_seed_upserts.py`:

```python
from backend.scripts._seed_core import (
    SeedType,
    SeedParamSpec,
    upsert_data_type,
)


@pytest.mark.asyncio
async def test_upsert_data_type_inserts_when_missing(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    flavor, _ = await upsert_system_flavor(
        transactional_session,
        SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14"]),
        kind.id,
    )
    spec = SeedType(
        code="varchar",
        params_schema={
            "length": SeedParamSpec(type="int", required=False, default=None)
        },
        render_template="varchar({length})",
    )
    obj, status = await upsert_data_type(transactional_session, spec, flavor.id)
    assert status == "inserted"
    assert obj.code == "varchar"
    assert obj.params_schema == {
        "length": {"type": "int", "required": False, "default": None}
    }


@pytest.mark.asyncio
async def test_upsert_data_type_updates_when_template_changes(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    flavor, _ = await upsert_system_flavor(
        transactional_session,
        SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14"]),
        kind.id,
    )
    await upsert_data_type(
        transactional_session,
        SeedType(code="bigint", params_schema={}, render_template="bigint"),
        flavor.id,
    )
    _, status = await upsert_data_type(
        transactional_session,
        SeedType(code="bigint", params_schema={}, render_template="int8"),
        flavor.id,
    )
    assert status == "updated"


@pytest.mark.asyncio
async def test_upsert_data_type_noop_when_unchanged(transactional_session):
    kind, _ = await upsert_system_kind(
        transactional_session, SeedKind(code="rdbms", name="R")
    )
    flavor, _ = await upsert_system_flavor(
        transactional_session,
        SeedFlavor(code="postgres14", name="PostgreSQL", versions=["14"]),
        kind.id,
    )
    spec = SeedType(code="bigint", params_schema={}, render_template="bigint")
    await upsert_data_type(transactional_session, spec, flavor.id)
    _, status = await upsert_data_type(transactional_session, spec, flavor.id)
    assert status == "unchanged"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-docker`
Expected: 3 new tests FAIL — `ImportError: upsert_data_type`.

- [ ] **Step 3: Implement**

Append to `backend/scripts/_seed_core.py`:

```python
def _param_specs_to_json(params: dict[str, SeedParamSpec]) -> dict[str, dict]:
    return {k: v.model_dump() for k, v in params.items()}


async def upsert_data_type(
    session: AsyncSession, spec: SeedType, flavor_id: uuid.UUID
) -> tuple[DataType, UpsertStatus]:
    from sqlalchemy import select

    target_params = _param_specs_to_json(spec.params_schema)

    stmt = select(DataType).where(
        DataType.system_flavor_id == flavor_id, DataType.code == spec.code
    )
    existing = (await session.execute(stmt)).scalars().first()

    if existing is None:
        obj = DataType(
            system_flavor_id=flavor_id,
            code=spec.code,
            params_schema=target_params,
            render_template=spec.render_template,
        )
        session.add(obj)
        await session.flush()
        return obj, "inserted"

    fields_changed = (
        existing.params_schema != target_params
        or existing.render_template != spec.render_template
    )

    if existing.deleted_at is not None:
        existing.deleted_at = None
        existing.params_schema = target_params
        existing.render_template = spec.render_template
        await session.flush()
        return existing, "restored"

    if fields_changed:
        existing.params_schema = target_params
        existing.render_template = spec.render_template
        await session.flush()
        return existing, "updated"

    return existing, "unchanged"
```

- [ ] **Step 4: Run tests**

Run: `make test-docker`
Expected: all upsert tests pass.

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/scripts/_seed_core.py tests/scripts/test_seed_upserts.py
git commit -m "feat(seed): add DataType upsert"
```

---

## Task 6: `seed_from_file` orchestrator

**Files:**
- Modify: `backend/scripts/_seed_core.py`
- Create: `tests/scripts/test_seed_runner.py`

- [ ] **Step 1: Write failing tests**

`tests/scripts/test_seed_runner.py`:

```python
import textwrap

import pytest
from sqlalchemy import select

from backend.models.data_type import DataType
from backend.models.system_flavor import SystemFlavor
from backend.models.system_kind import SystemKind
from backend.scripts._seed_core import seed_from_file


SAMPLE_YAML = textwrap.dedent(
    """
    kind: {code: rdbms, name: Relational Database}
    flavor:
      code: postgres14
      name: PostgreSQL
      vendor: PGDG
      versions: ["14", "15"]
    types:
      - code: bigint
        params_schema: {}
        render_template: bigint
      - code: varchar
        params_schema:
          length: {type: int, required: false, default: null}
        render_template: "varchar({length})"
    """
)


@pytest.mark.asyncio
async def test_seed_from_file_inserts_everything(transactional_session, tmp_path):
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)

    report = await seed_from_file(transactional_session, p)

    assert report.kind == "inserted"
    assert report.flavor == "inserted"
    assert report.types_inserted == 2
    assert report.types_updated == 0
    assert report.types_unchanged == 0

    kinds = (await transactional_session.execute(select(SystemKind))).scalars().all()
    assert len(kinds) == 1
    flavors = (
        await transactional_session.execute(select(SystemFlavor))
    ).scalars().all()
    assert len(flavors) == 1
    types = (await transactional_session.execute(select(DataType))).scalars().all()
    assert {t.code for t in types} == {"bigint", "varchar"}


@pytest.mark.asyncio
async def test_seed_from_file_is_idempotent(transactional_session, tmp_path):
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)

    await seed_from_file(transactional_session, p)
    report = await seed_from_file(transactional_session, p)

    assert report.kind == "unchanged"
    assert report.flavor == "unchanged"
    assert report.types_inserted == 0
    assert report.types_unchanged == 2


@pytest.mark.asyncio
async def test_seed_from_file_updates_changed_template(
    transactional_session, tmp_path
):
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)
    await seed_from_file(transactional_session, p)

    modified = SAMPLE_YAML.replace("render_template: bigint", "render_template: int8")
    p.write_text(modified)

    report = await seed_from_file(transactional_session, p)
    assert report.types_updated == 1
    assert report.types_unchanged == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-docker`
Expected: FAIL — `ImportError: seed_from_file`.

- [ ] **Step 3: Implement orchestrator**

Append to `backend/scripts/_seed_core.py`:

```python
from pathlib import Path


async def seed_from_file(session: AsyncSession, path: Path | str) -> SeedReport:
    seed = load_seed_file(path)
    report = SeedReport()

    kind_obj, kind_status = await upsert_system_kind(session, seed.kind)
    report.kind = kind_status

    flavor_obj, flavor_status = await upsert_system_flavor(
        session, seed.flavor, kind_obj.id
    )
    report.flavor = flavor_status

    for type_spec in seed.types:
        _, t_status = await upsert_data_type(session, type_spec, flavor_obj.id)
        if t_status == "inserted":
            report.types_inserted += 1
        elif t_status == "updated":
            report.types_updated += 1
        elif t_status == "restored":
            report.types_restored += 1
        elif t_status == "unchanged":
            report.types_unchanged += 1

    return report
```

- [ ] **Step 4: Run tests**

Run: `make test-docker`
Expected: all `test_seed_runner.py` tests pass.

- [ ] **Step 5: Format + commit**

```bash
make format
git add backend/scripts/_seed_core.py tests/scripts/test_seed_runner.py
git commit -m "feat(seed): add seed_from_file orchestrator"
```

---

## Task 7: CLI entry point

**Files:**
- Create: `backend/scripts/seed_data_types.py`
- Modify: `tests/scripts/test_seed_runner.py`

- [ ] **Step 1: Write failing tests for CLI main**

Append to `tests/scripts/test_seed_runner.py`:

```python
from backend.scripts.seed_data_types import _main as seed_main


@pytest.mark.asyncio
async def test_cli_dry_run_rolls_back(tmp_path):
    """Dry run: seed runs inside a UoW and rolls back."""
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)

    report = await seed_main(file=p, dry_run=True)
    assert report.types_inserted == 2

    # Verify nothing persisted.
    from sqlalchemy import select
    from backend.db.uow import UnitOfWork
    from backend.models.data_type import DataType

    async with UnitOfWork() as uow:
        rows = (await uow.session.execute(select(DataType))).scalars().all()
        assert all(r.code not in {"bigint", "varchar"} for r in rows)


@pytest.mark.asyncio
async def test_cli_commit_persists(tmp_path):
    """Real commit path persists. Test cleans up after itself."""
    p = tmp_path / "seed.yaml"
    p.write_text(SAMPLE_YAML)

    from sqlalchemy import delete, select
    from backend.db.uow import UnitOfWork
    from backend.models.data_type import DataType
    from backend.models.system_flavor import SystemFlavor
    from backend.models.system_kind import SystemKind

    try:
        report = await seed_main(file=p, dry_run=False)
        assert report.types_inserted == 2

        async with UnitOfWork() as uow:
            rows = (await uow.session.execute(select(DataType))).scalars().all()
            assert {"bigint", "varchar"}.issubset({r.code for r in rows})
    finally:
        async with UnitOfWork() as uow:
            await uow.session.execute(
                delete(DataType).where(DataType.code.in_(["bigint", "varchar"]))
            )
            await uow.session.execute(
                delete(SystemFlavor).where(SystemFlavor.code == "postgres14")
            )
            await uow.session.execute(
                delete(SystemKind).where(SystemKind.code == "rdbms")
            )
```

Note: the commit test bypasses the `transactional_session` fixture (it opens its own UoW), so it cleans up in a `finally` to keep the suite repeatable.

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-docker`
Expected: FAIL — `ImportError: seed_data_types`.

- [ ] **Step 3: Implement CLI**

`backend/scripts/seed_data_types.py`:

```python
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from backend.db.uow import UnitOfWork
from backend.scripts._seed_core import SeedReport, seed_from_file


async def _main(file: Path, dry_run: bool = False) -> SeedReport:
    uow = UnitOfWork()
    await uow.__aenter__()
    try:
        report = await seed_from_file(uow.session, file)
        if dry_run:
            await uow.rollback()
        else:
            await uow.commit()
        return report
    finally:
        await uow.session.close()


def _print_report(report: SeedReport, dry_run: bool) -> None:
    prefix = "[DRY RUN] " if dry_run else ""
    print(
        f"{prefix}kind={report.kind} flavor={report.flavor} "
        f"types: +{report.types_inserted} ~{report.types_updated} "
        f"={report.types_unchanged} restored={report.types_restored}"
    )


def _entry() -> None:
    parser = argparse.ArgumentParser(description="Seed data types from a YAML file.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(_main(args.file, dry_run=args.dry_run))
    _print_report(report, dry_run=args.dry_run)


if __name__ == "__main__":
    _entry()
```

- [ ] **Step 4: Run tests**

Run: `make test-docker`
Expected: all tests pass (runner + CLI).

- [ ] **Step 5: Manual smoke test**

Create `/tmp/seed.yaml` with `SAMPLE_YAML` content and run:

```bash
uv run python -m backend.scripts.seed_data_types --file /tmp/seed.yaml --dry-run
```

Expected stdout line: `[DRY RUN] kind=inserted flavor=inserted types: +2 ~0 =0 restored=0`

- [ ] **Step 6: Format + commit**

```bash
make format
git add backend/scripts/seed_data_types.py tests/scripts/test_seed_runner.py
git commit -m "feat(seed): add CLI entry for seed_data_types"
```

---

## Task 8: Generate + commit `postgres14.yaml`

This task is **data**, not code. No TDD loop; instead, we validate by loading.

**Files:**
- Create: `backend/scripts/data/__init__.py`
- Create: `backend/scripts/data/postgres14.yaml`
- Modify: `tests/scripts/test_seed_runner.py`

- [ ] **Step 1: Source data via Context7**

Use the `mcp__948486f4-9092-4c7c-be93-92118ec7d354__resolve-library-id` tool to resolve `PostgreSQL`, then `mcp__948486f4-9092-4c7c-be93-92118ec7d354__query-docs` with a query like: "List all built-in data types in PostgreSQL 14 chapter 8, with each type's name, parameters (if any), and native SQL rendering syntax." Cross-check against the canonical PG14 types list below.

Expected type `code` values (the YAML must contain exactly these 52 codes, no more, no less):

```
smallint, integer, bigint, decimal, numeric, real, double, smallserial, serial,
bigserial, money, char, varchar, text, bytea, date, time, timetz, timestamp,
timestamptz, interval, boolean, enum, point, line, lseg, box, path, polygon,
circle, inet, cidr, macaddr, macaddr8, bit, varbit, tsvector, tsquery, uuid,
xml, json, jsonb, array, int4range, int8range, numrange, tsrange, tstzrange,
daterange, oid, pg_lsn, txid_snapshot
```

Params to include:
- `numeric` / `decimal`: `precision` (int, optional), `scale` (int, optional)
- `char` / `varchar`: `length` (int, optional)
- `time` / `timetz` / `timestamp` / `timestamptz`: `precision` (int, optional)
- `interval`: `precision` (int, optional)
- `bit` / `varbit`: `length` (int, optional)
- All others: `params_schema: {}`

`render_template`:
- `numeric` → `numeric({precision},{scale})`
- `varchar` → `varchar({length})`
- `char` → `char({length})`
- `timestamp` → `timestamp({precision})`, `timestamptz` → `timestamp({precision}) with time zone`, same pattern for `time`/`timetz`
- `interval` → `interval({precision})`
- `bit` → `bit({length})`, `varbit` → `bit varying({length})`
- All simple types → code itself (`bigint` → `bigint`, `jsonb` → `jsonb`)
- `array`, `enum` → `null` (rendered by custom logic later, not a template)

- [ ] **Step 2: Write the YAML file**

Create `backend/scripts/data/postgres14.yaml`. Header:

```yaml
kind:
  code: rdbms
  name: Relational Database
flavor:
  code: postgres14
  name: PostgreSQL
  vendor: PostgreSQL Global Development Group
  versions: ["14"]
types:
  # Numeric
  - code: smallint
    params_schema: {}
    render_template: smallint
  - code: integer
    params_schema: {}
    render_template: integer
  - code: bigint
    params_schema: {}
    render_template: bigint
  - code: decimal
    params_schema:
      precision: {type: int, required: false, default: null}
      scale:     {type: int, required: false, default: null}
    render_template: "decimal({precision},{scale})"
  - code: numeric
    params_schema:
      precision: {type: int, required: false, default: null}
      scale:     {type: int, required: false, default: null}
    render_template: "numeric({precision},{scale})"
  # ... continue through all 52 codes per Step 1 list
```

Fill in remaining 47 entries following the rules in Step 1. Create `backend/scripts/data/__init__.py` as empty file.

- [ ] **Step 3: Add a static validation test**

Append to `tests/scripts/test_seed_runner.py`:

```python
from pathlib import Path

from backend.scripts._seed_core import load_seed_file

POSTGRES14_YAML = Path("backend/scripts/data/postgres14.yaml")

EXPECTED_PG14_TYPE_CODES = {
    "smallint", "integer", "bigint", "decimal", "numeric", "real", "double",
    "smallserial", "serial", "bigserial", "money",
    "char", "varchar", "text", "bytea",
    "date", "time", "timetz", "timestamp", "timestamptz", "interval",
    "boolean", "enum",
    "point", "line", "lseg", "box", "path", "polygon", "circle",
    "inet", "cidr", "macaddr", "macaddr8",
    "bit", "varbit",
    "tsvector", "tsquery",
    "uuid", "xml", "json", "jsonb", "array",
    "int4range", "int8range", "numrange", "tsrange", "tstzrange", "daterange",
    "oid", "pg_lsn", "txid_snapshot",
}


def test_postgres14_yaml_loads_and_covers_all_expected_codes():
    parsed = load_seed_file(POSTGRES14_YAML)
    assert parsed.flavor.code == "postgres14"
    codes = {t.code for t in parsed.types}
    missing = EXPECTED_PG14_TYPE_CODES - codes
    extra = codes - EXPECTED_PG14_TYPE_CODES
    assert not missing, f"Missing types: {sorted(missing)}"
    assert not extra, f"Unexpected types: {sorted(extra)}"
```

- [ ] **Step 4: Run the validation test**

Run: `cd backend && uv run pytest ../tests/scripts/test_seed_runner.py::test_postgres14_yaml_loads_and_covers_all_expected_codes -v`
(This test is pure file parsing — no DB — so it runs outside Docker too.)
Expected: PASS.

- [ ] **Step 5: Full end-to-end smoke test against the real file**

Append to `tests/scripts/test_seed_runner.py`:

```python
@pytest.mark.asyncio
async def test_seed_from_real_postgres14_yaml(transactional_session):
    report = await seed_from_file(transactional_session, POSTGRES14_YAML)
    assert report.kind in {"inserted", "unchanged", "updated", "restored"}
    assert report.types_inserted == len(EXPECTED_PG14_TYPE_CODES)
```

Run: `make test-docker`
Expected: PASS.

- [ ] **Step 6: Manual dry-run against real DB**

```bash
make up   # if not running
uv run python -m backend.scripts.seed_data_types \
  --file backend/scripts/data/postgres14.yaml --dry-run
```

Expected: `[DRY RUN] kind=inserted flavor=inserted types: +52 ~0 =0 restored=0` (or `unchanged` counts if already seeded).

- [ ] **Step 7: Format + commit**

```bash
make format
git add backend/scripts/data/ tests/scripts/test_seed_runner.py
git commit -m "feat(seed): add postgres14 data types YAML"
```

---

## Task 9: Wire into real seed workflow (docs only)

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a Commands table row + short section**

Edit `CLAUDE.md`. Under the `## Commands` table add:

```markdown
| `uv run python -m backend.scripts.seed_data_types --file backend/scripts/data/postgres14.yaml` | Seed PG14 data types |
```

Under `## Conventions` add:

```markdown
### Data type seeding

Data types are pre-loaded per flavor from YAML files in `backend/scripts/data/`. Flavor `code` = min supported version; `versions` lists all compatible versions. Re-run `seed_data_types.py` after editing a YAML — it is idempotent. Removing a type from YAML does NOT delete the row (protects existing `TypeInstance` FKs); prune manually if required.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document data type seeding workflow"
```

---

## Self-Review Notes

**Spec coverage check:**
- YAML schema → Task 1.
- Type coverage (52 PG14 built-ins) → Task 8 Step 1/2 + validation test.
- Flavor code convention (`postgres14`, `versions:["14","15"]`) → Task 4 tests + Task 8 YAML.
- Idempotency + upsert policy (no auto-delete) → Tasks 3–5, Task 6 idempotency test.
- Soft-delete restore → Task 3 restore test.
- Transactional commit / dry-run → Task 7.
- Report counts → Tasks 3/6/7.
- Test location `tests/scripts/` + `make test-docker` → all tasks.

**Known trade-offs documented in spec, re-confirmed here:**
- `params_schema` is a custom shape, not JSON Schema — accepted.
- Removed-from-YAML means "keep row" — Task 6 has no test that asserts deletion, matching spec.
- Task 8 Step 1 requires manual curation from Context7 output; the validation test enforces code coverage so drift is caught.
