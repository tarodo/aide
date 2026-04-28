# Bugfix + Test Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close three follow-ups from the test-coverage-gaps branch: fix the dead-rename bug in `DatasetSchemaService.update()` (T1), remove duplicate `FieldLink` import alias (T2), and promote lake-sync test helpers into a shared module (T3).

**Architecture:** Three independent, surgical changes. T1 is the only production-code change — replace the buggy `update()` override with a complete reimplementation that mirrors `create()`'s explicit-rewrite pattern. T2 is import-cleanup. T3 extracts four module-level helpers from `tests/api/test_lake_sync.py` into `tests/_helpers.py` and re-imports from both consumer files.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, pytest-asyncio.

---

## Background

The test-coverage-gaps branch (merged in `70783d4`) discovered a real production bug and left two minor cleanups:

1. **Bug** — `backend/services/dataset_schema.py:101-113` builds a renamed `update_data` dict and then calls `super().update(uow, obj_id, obj_in, updater_id)` passing the *original* `obj_in`. The base `GenericService.update()` (`backend/services/base.py:175-214`) re-dumps `obj_in` from scratch via `model_dump(exclude_unset=True)`, which produces `{"schema_": ...}` (Pydantic field name; `serialization_alias="schema_"` reinforces this) and then `setattr(db_obj, "schema_", value)`. The model column is `schema`, not `schema_` — so PATCH `/dataset-schemas/{id}` with body `{"schema": {...}}` silently fails to write the JSONB column. The local `update_data` is dead code.

   The locking-in test at `tests/services/test_dataset_schema_service.py:154-183` is currently `xfail(strict=True)`. Once the bug is fixed, it must xpass and the marker must be removed (strict=True forces this).

2. **Dup import** — `tests/services/test_field_link_service.py:12-13` imports `FieldLink` and the same class as `FieldLinkModel`. The alias is used at exactly one site (line 397). Drop the alias, use `FieldLink` everywhere.

3. **Helper duplication** — `tests/api/test_lake_sync.py` defines four module-level helpers (`_seed_pg_and_iceberg`, `_create_pg_system`, `_create_lake_system`, `_make_source_dataset`). `tests/services/test_lake_sync_service.py` cross-imports them from `tests.api.test_lake_sync` — the only cross-test-layer import in the repo. CLAUDE.md says: "When adding a 3rd copy of one of these helpers, consider promoting to `tests/conftest.py` or `tests/_helpers.py`." We have 2 consumers, but the cross-layer import is fragile (rename in test_lake_sync.py silently breaks service tests). Promote to `tests/_helpers.py` now.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `backend/services/dataset_schema.py:101-113` | Replace `update()` override with full reimplementation that mirrors `create()`. |
| Modify | `tests/services/test_dataset_schema_service.py:154-183` | Remove `@pytest.mark.xfail` marker on `test_update_renames_schema_underscore_to_schema`. |
| Modify | `tests/services/test_field_link_service.py:12-13, 397` | Drop `FieldLinkModel` alias, rename usage. |
| Create | `tests/_helpers.py` | Shared lake-sync seed helpers. |
| Modify | `tests/api/test_lake_sync.py:69-198` | Replace local helper definitions with re-exports from `tests._helpers`. |
| Modify | `tests/services/test_lake_sync_service.py:22-27` | Switch import source from `tests.api.test_lake_sync` to `tests._helpers`. |

---

## Conventions reminder

- Tests run inside Docker via `make test-docker`. Narrow with `PYTEST_ARGS="-v tests/path/...py" make test-docker`.
- Stop stale test DB containers before running: `docker stop test_cov-db-test-1 aide-db-test-1` (whichever is bound to 5433). Inspect with `lsof -i :5433`.
- After every code edit run `make format` (black + ruff --fix).
- Commit messages: imperative, ≤50 chars, Conventional Commits, no AI attribution trailers.
- The `transactional_session` fixture from `tests/conftest.py` is auto-applied; rolls back per-test.
- One DB instance only on 5433 — if blocked, stop the holder.

---

## Task 1: Fix `DatasetSchemaService.update()` dead-rename bug

**Files:**
- Modify: `backend/services/dataset_schema.py:101-113`
- Modify: `tests/services/test_dataset_schema_service.py:154-183`

The fix replaces the partial override with a full reimplementation that mirrors `create()` (already correct in this file at lines 79-99). This avoids the trap of `super().update()` re-dumping `obj_in`. Pattern is locally consistent — both overrides now own their full lifecycle.

**Why a full override and not a `super()` shim?** Two alternatives were considered:

- *Mutate `obj_in` before delegating.* Pydantic v2 `model_copy(update={"schema": ...})` would set a non-field attribute (since `schema` is the alias, the actual field is `schema_`); `setattr(obj_in, "schema_", value)` works but the field is already present. The cleaner intent is "rename serialization key", which `model_dump(by_alias=True)` would do — but flipping that on the base service affects every other service.
- *Add a `_normalize_update_data` hook to `GenericService`.* Wider blast radius; touches every subclass.

The full local override mirrors what `create()` already does, so the file's two methods are now symmetric.

- [ ] **Step 1: Confirm the failing (xfail-strict) test exists and is currently xfail**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_schema_service.py::test_update_renames_schema_underscore_to_schema" make test-docker`

Expected: `1 xfailed`. The strict marker means a fix-induced xpass would fail this run — which is the goal of step 4.

- [ ] **Step 2: Replace the buggy `update()` override**

Edit `backend/services/dataset_schema.py`. Find this exact block at lines 101-113:

```python
    async def update(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        obj_in: DatasetSchemaUpdate,
        updater_id: uuid.UUID | None = None,
    ) -> DatasetSchemaRead:
        """Update an existing object."""
        update_data = obj_in.model_dump(exclude_unset=True)
        if "schema_" in update_data:
            update_data["schema"] = update_data.pop("schema_")

        return await super().update(uow, obj_id, obj_in, updater_id)
```

Replace with:

```python
    async def update(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        obj_in: DatasetSchemaUpdate,
        updater_id: uuid.UUID | None = None,
    ) -> DatasetSchemaRead:
        """Update an existing object.

        Overrides the generic update to rename the Pydantic alias `schema_`
        (BaseModel.schema clash) to the SA column name `schema`. We can't
        delegate to ``super().update()`` because it re-dumps ``obj_in`` and
        loses the rename — see the symmetric handling in ``create()``.
        """
        update_data = obj_in.model_dump(exclude_unset=True)
        if "schema_" in update_data:
            update_data["schema"] = update_data.pop("schema_")
        client_row_version = update_data.pop("row_version", None)

        async with uow:
            repo: BaseRepository[DatasetSchema] = self._get_repository(uow.session)
            db_obj = await repo.get(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)

            if client_row_version is not None and hasattr(db_obj, "row_version"):
                if db_obj.row_version != client_row_version:
                    raise AppException(errors.VERSION_CONFLICT)

            await self._pre_update(uow, db_obj, obj_in, updater_id)

            for field, value in update_data.items():
                setattr(db_obj, field, value)

            if hasattr(db_obj, "row_version"):
                db_obj.row_version += 1

            if updater_id and hasattr(db_obj, "updated_by"):
                setattr(db_obj, "updated_by", updater_id)

            updated_obj = await repo.update(db_obj=db_obj)
            return self.read_schema.model_validate(updated_obj)
```

The added imports are already present: `errors`, `AppException`, `BaseRepository`, `UnitOfWork`, `DatasetSchema` are all imported at the top of the file (lines 6-12). No new imports needed.

- [ ] **Step 3: Remove the `xfail` marker**

Edit `tests/services/test_dataset_schema_service.py:154-162`. Find:

```python
@pytest.mark.xfail(
    reason=(
        "DatasetSchemaService.update renames schema_ -> schema in a local dict "
        "but then delegates to super().update(obj_in=...) which re-dumps obj_in "
        "from scratch — the rename is dead code. Bug in "
        "backend/services/dataset_schema.py:109-113."
    ),
    strict=True,
)
@pytest.mark.asyncio
async def test_update_renames_schema_underscore_to_schema(
```

Delete the `@pytest.mark.xfail(...)` decorator entirely (lines 154-162) so only `@pytest.mark.asyncio` remains immediately above the function.

- [ ] **Step 4: Run the now-fixed test**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_schema_service.py::test_update_renames_schema_underscore_to_schema" make test-docker`

Expected: `1 passed`. (If you see `1 xpassed` instead, you forgot Step 3 — strict=True converts xpass to failure; remove the xfail marker.)

- [ ] **Step 5: Run the full dataset-schema service test file**

Run: `PYTEST_ARGS="-v tests/services/test_dataset_schema_service.py" make test-docker`

Expected: all tests pass (the file had 6 tests including 5 added in T7; with the xfail removed, expect `6 passed, 0 xfailed`).

- [ ] **Step 6: Format**

Run: `make format`

- [ ] **Step 7: Commit**

```bash
git add backend/services/dataset_schema.py tests/services/test_dataset_schema_service.py
git commit -m "fix(schema): persist schema_ rename in update()"
```

---

## Task 2: Drop duplicate `FieldLink` import alias

**Files:**
- Modify: `tests/services/test_field_link_service.py:12-13, 397`

The alias `FieldLinkModel` is used at exactly one site (line 397, inside `test_bulk_create_happy_path`). Removing it leaves `FieldLink` (already imported on line 12) as the canonical name.

- [ ] **Step 1: Drop the alias import**

Edit `tests/services/test_field_link_service.py`. Find lines 12-13:

```python
from backend.models.field_link import FieldLink
from backend.models.field_link import FieldLink as FieldLinkModel
```

Replace with just the first line:

```python
from backend.models.field_link import FieldLink
```

- [ ] **Step 2: Update the call site**

In the same file at line 397, find:

```python
    created_obj = FieldLinkModel(
```

Replace with:

```python
    created_obj = FieldLink(
```

- [ ] **Step 3: Confirm no other `FieldLinkModel` references remain**

Run: `grep -n "FieldLinkModel" tests/services/test_field_link_service.py`

Expected: no output (zero matches).

- [ ] **Step 4: Run the file**

Run: `PYTEST_ARGS="-v tests/services/test_field_link_service.py" make test-docker`

Expected: all tests pass (17/17 — the count from T6).

- [ ] **Step 5: Format**

Run: `make format`

- [ ] **Step 6: Commit**

```bash
git add tests/services/test_field_link_service.py
git commit -m "refactor(test): drop redundant FieldLinkModel alias"
```

---

## Task 3: Promote lake-sync helpers to `tests/_helpers.py`

**Files:**
- Create: `tests/_helpers.py`
- Modify: `tests/api/test_lake_sync.py:69-198` (replace local definitions with re-exports)
- Modify: `tests/services/test_lake_sync_service.py:22-27` (switch import source)

The four helpers (`_seed_pg_and_iceberg`, `_create_pg_system`, `_create_lake_system`, `_make_source_dataset`) move verbatim. Function bodies don't change — only the home file. Both consumer files re-import from the new module.

The leading underscore is preserved — these are internal test utilities, not a public API.

- [ ] **Step 1: Create `tests/_helpers.py`**

Create the new file with this exact content:

```python
"""Shared test helpers.

Currently hosts lake-sync seed helpers used by both the API-layer tests
(``tests/api/test_lake_sync.py``) and the service-layer tests
(``tests/services/test_lake_sync_service.py``). Promoted from the API
test file once the second consumer arrived.

CLAUDE.md guidance: promote to this module when a helper has 3+ copies
or two consumers in different layers. The lake-sync helpers hit the
second condition.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.dataset import Dataset, DatasetRdbms
from backend.models.dataset_schema import DatasetSchema
from backend.models.field import Field
from backend.models.field_binding import FieldBinding
from backend.models.system import System
from backend.models.system_flavor import SystemFlavor
from backend.models.type_instance import TypeInstance
from backend.scripts._seed_cast_rules_core import (
    seed_from_file as seed_casts_from_file,
)
from backend.scripts._seed_core import seed_from_file as seed_dt_from_file


async def _seed_pg_and_iceberg(session: AsyncSession) -> None:
    await seed_dt_from_file(session, Path("backend/scripts/data/postgres14.yaml"))
    await seed_dt_from_file(session, Path("backend/scripts/data/iceberg_v2.yaml"))
    await seed_casts_from_file(
        session, Path("backend/scripts/data/casts_pg14_to_iceberg_v2.yaml")
    )


async def _create_pg_system(session: AsyncSession) -> System:
    flavor = (
        (
            await session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "postgres14")
            )
        )
        .scalars()
        .first()
    )
    sys = System(
        code=f"pg-src-{uuid.uuid4().hex[:6]}",
        name="PG Source",
        flavor_id=flavor.id,
    )
    session.add(sys)
    await session.flush()
    return sys


async def _create_lake_system(session: AsyncSession) -> System:
    flavor = (
        (
            await session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "iceberg_v2")
            )
        )
        .scalars()
        .first()
    )
    sys = System(
        code=f"lake-{uuid.uuid4().hex[:6]}",
        name="Lake",
        flavor_id=flavor.id,
    )
    session.add(sys)
    await session.flush()
    return sys


async def _make_source_dataset(
    session: AsyncSession, system: System
) -> tuple[Dataset, DatasetSchema, list[Field]]:
    """Create a minimal pg14 source: id bigint, amount numeric(10,2), tags array<int>."""
    ds = DatasetRdbms(
        kind="rdbms",
        system_id=system.id,
        object_name="public.users",
        schema_name="public",
        table_name="users",
        layer="raw",
    )
    session.add(ds)
    await session.flush()

    schema = DatasetSchema(dataset_id=ds.id, version_num=1)
    session.add(schema)
    await session.flush()

    pg_flavor = (
        (
            await session.execute(
                select(SystemFlavor).where(SystemFlavor.code == "postgres14")
            )
        )
        .scalars()
        .first()
    )
    from backend.models.data_type import DataType

    pg_types = {
        dt.code: dt
        for dt in (
            await session.execute(
                select(DataType).where(DataType.system_flavor_id == pg_flavor.id)
            )
        ).scalars()
    }

    fields: list[Field] = []
    for idx, (name, dt_code, params, slot_children) in enumerate(
        [
            ("id", "bigint", {}, []),
            ("amount", "numeric", {"precision": 10, "scale": 2}, []),
            ("tags", "array", {}, [("item", "integer", {})]),
        ]
    ):
        fld = Field(dataset_id=ds.id, name=name, origin="mapped")
        session.add(fld)
        await session.flush()
        fields.append(fld)

        root_ti = TypeInstance(
            data_type_id=pg_types[dt_code].id,
            type_params=params or None,
            slot=None,
        )
        session.add(root_ti)
        await session.flush()
        for slot, child_code, child_params in slot_children:
            child_ti = TypeInstance(
                data_type_id=pg_types[child_code].id,
                type_params=child_params or None,
                slot=slot,
                parent_id=root_ti.id,
            )
            session.add(child_ti)
            await session.flush()

        binding = FieldBinding(
            field_id=fld.id,
            dataset_schema_id=schema.id,
            position=idx,
            is_nullable=(name != "id"),
            type_instance_id=root_ti.id,
        )
        session.add(binding)
        await session.flush()

    return ds, schema, fields
```

- [ ] **Step 2: Update `tests/api/test_lake_sync.py` — strip the four local helper definitions**

Edit `tests/api/test_lake_sync.py`. Delete lines 66-198 inclusive (the comment `# ---------------- helpers (kept inline per CLAUDE.md guidance) ----------------` plus the four `async def` blocks for `_seed_pg_and_iceberg`, `_create_pg_system`, `_create_lake_system`, `_make_source_dataset`). The next surviving line should be the `# ---------------- tests ----------------` comment that precedes the first test.

After the delete, also remove these now-unused top-level imports from `tests/api/test_lake_sync.py` (only if they are not referenced anywhere else in the file — verify by grep before removing):

```python
from pathlib import Path
from sqlalchemy import select
from backend.models.dataset import Dataset, DatasetHive
from backend.models.dataset_link import DatasetLink
from backend.models.field_binding import FieldBinding
from backend.models.field_link import FieldLink
from backend.models.system import System
from backend.models.system_flavor import SystemFlavor
from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)
from backend.models.type_instance import TypeInstance
from backend.scripts._seed_cast_rules_core import (
    seed_from_file as seed_casts_from_file,
)
from backend.scripts._seed_core import seed_from_file as seed_dt_from_file
```

For each of those imports, run: `grep -n "<symbol>" tests/api/test_lake_sync.py`. If any test body still references it (e.g. `DatasetHive`, `TechFieldTemplate` etc. — they DO appear in tests like `test_lake_sync_with_tech_template`), keep the import. Only drop the imports that become orphans after the helper removal. Specifically: `Path`, `seed_dt_from_file`, `seed_casts_from_file` will become unused. The model imports (`Dataset`, `DatasetHive`, `DatasetLink`, `FieldBinding`, `FieldLink`, `System`, `SystemFlavor`, `TechFieldTemplate`, `TechFieldTemplateField`, `TypeInstance`) are referenced in test bodies and must stay.

Then add this single import near the existing top-of-file imports:

```python
from tests._helpers import (
    _create_lake_system,
    _create_pg_system,
    _make_source_dataset,
    _seed_pg_and_iceberg,
)
```

- [ ] **Step 3: Update `tests/services/test_lake_sync_service.py` — switch import source**

Edit `tests/services/test_lake_sync_service.py`. Find this block at lines 22-27:

```python
# Re-use API-test helpers via direct import (kept inline per CLAUDE.md guidance —
# promote to tests/_helpers.py if a 3rd copy is needed).
from tests.api.test_lake_sync import (
    _create_lake_system,
    _create_pg_system,
    _make_source_dataset,
    _seed_pg_and_iceberg,
)
```

Replace with:

```python
from tests._helpers import (
    _create_lake_system,
    _create_pg_system,
    _make_source_dataset,
    _seed_pg_and_iceberg,
)
```

- [ ] **Step 4: Run both consumer test files**

Run: `PYTEST_ARGS="-v tests/api/test_lake_sync.py tests/services/test_lake_sync_service.py" make test-docker`

Expected: all tests pass (api file has 7 tests, service file has 7 tests = 14 passed). If any test fails with `ImportError` or `NameError`, you removed an import in step 2 that was actually still in use — restore it.

- [ ] **Step 5: Format**

Run: `make format`

This may also drop additional unused imports via `ruff --fix` (the `F401` rule). Re-run the previous command after format if ruff modifies the test files.

- [ ] **Step 6: Commit**

```bash
git add tests/_helpers.py tests/api/test_lake_sync.py tests/services/test_lake_sync_service.py
git commit -m "refactor(test): promote lake-sync helpers"
```

---

## Task 4: Final verification

**Files:**
- (none — verification only)

- [ ] **Step 1: Run full test suite**

Run: `PYTEST_ARGS="-q tests/" make test-docker`

Expected: `579 passed, 0 xfailed` (was `578 passed, 1 xfailed` after Task 1 closes the xfail; nothing else changes test count). If you see `1 xfailed`, the marker on `test_update_renames_schema_underscore_to_schema` was not removed (Step 3 of Task 1).

- [ ] **Step 2: Confirm coverage moved**

Run: `PYTEST_ARGS="-q --cov=backend --cov-report=term tests/" make test-docker | tail -30`

Expected: `backend/services/dataset_schema.py` coverage ≥ 95% (was 90% — the previously-untested update branch is now covered).

- [ ] **Step 3: Confirm no stray xfails remain in changed files**

Run: `grep -rn "xfail" tests/`

Expected: no matches (project did not have other xfails before this branch).

If matches appear, investigate — they may be pre-existing markers from outside this plan. Do not remove them.

- [ ] **Step 4: No final commit needed**

This task only verifies; no files change.

---

## Self-Review

**1. Spec coverage:**

| Follow-up | Task |
|-----------|------|
| Bug: `DatasetSchemaService.update()` dead-rename | Task 1 |
| Dup import `FieldLink as FieldLinkModel` | Task 2 |
| Cross-test import → promote helpers | Task 3 |
| Verify everything still passes | Task 4 |

All three follow-ups have a task. Task 4 verifies the merged result.

**2. Placeholder scan:** None — every step contains exact code, exact paths, exact commands, and exact expected output.

**3. Type consistency:**
- `update()` signature in Task 1 matches the existing `create()` signature pattern (same kwargs, same return type).
- `_helpers.py` function signatures preserve the originals from `tests/api/test_lake_sync.py:69-198` exactly (same types, same return tuple shape).
- Both consumer files import the same four names — no naming drift between Tasks 2 and 3.

**Edge cases:**
- Task 1 step 4 explicitly calls out the `xpassed` failure mode (`strict=True` converts xpass to failure if Step 3 is skipped).
- Task 3 step 2 cautions about `ruff --fix` removing imports — re-running tests after format catches that.
- Task 3 step 2 lists the model imports that must stay vs. the orphan imports that will go (`Path`, `seed_dt_from_file`, `seed_casts_from_file`).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-bugfix-and-cleanup.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks
**2. Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints

Which approach?
