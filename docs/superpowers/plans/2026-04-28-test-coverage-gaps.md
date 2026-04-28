# Test Coverage Gaps — Critical Closures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close critical test coverage gaps in `backend/` (auth, repositories, lake-sync, field/schema services) without padding meaningless line coverage.

**Architecture:** Each task adds one focused test module (or extends an existing one) following the project's two test layers — DB-backed repository/API tests via `transactional_session` fixture, and mocked-UoW service tests. No production code changes.

**Tech Stack:** pytest, pytest-asyncio, SQLAlchemy 2.0 async, FastAPI/httpx ASGITransport, `unittest.mock` (AsyncMock/MagicMock), Alembic.

---

## Coverage baseline (run on `main` 2026-04-28)

Total backend coverage: **87%** (515 passed). Targeted gaps below.

| Module | Cov | Critical gap |
|--------|-----|---------------|
| `services/lake_sync.py` | 36% | orchestrator branches: NO_SOURCE_SCHEMA, SYSTEM_NOT_FOUND, TECH_FIELD_TEMPLATE_LAYER_MISMATCH, TECH_TYPE_CODE_NOT_RESOLVABLE |
| `repositories/base.py` | 66% | `_apply_filters` LT/LTE/IN/LIKE branches; `SoftDeleteRepository.restore` / `get_including_deleted` / paginated `include_deleted=True` |
| `services/auth_service.py` | 67% | refresh-token flow: invalid/revoked/expired token, inactive user, rotation success, revoke single + revoke-all |
| `services/field.py` | 70% | `_validate_parent` (not-found + dataset-mismatch); `_check_circular_reference`; `get_tree`, `get_children`; pre_create duplicate name |
| `services/dataset_schema.py` | 75% | `_pre_delete` blocking on pinned `DatasetLink`; `schema_` → `schema` rename in create + update |
| `repositories/refresh_token.py` | 75% | `revoke_all_for_user`, `delete_expired` |
| `services/field_link.py` | 76% | `bulk_create` (empty + happy + invariant errors); `delete` not-found |
| `repositories/type_instance.py` | 79% | `get_by_parent_and_slot`, `get_children`, `get_tree` (recursive eager load) |

**Out of scope** (intentionally skipped — non-critical, scripts, or trivial getters):

- `backend/scripts/seed_cast_rules.py`, `ensure_superuser.py` — single-shot operator scripts.
- `backend/scripts/migrate_lineage_pins.py` — already at 55% via `tests/scripts/test_migrate_lineage_pins.py`.
- Model files at 92–99% — uncovered lines are `__repr__` strings and `Mapped[uuid.UUID]` declarations; cosmetic.

---

## File map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `tests/services/test_auth_service_refresh.py` | Refresh-token flow unit tests (mocked UoW). |
| Create | `tests/repositories/test_refresh_token_repository.py` | DB-backed `revoke_all_for_user` + `delete_expired`. |
| Create | `tests/repositories/test_base_filters.py` | `_apply_filters` per-operator + `_apply_sort` invalid column. |
| Create | `tests/repositories/test_soft_delete_repository.py` | `restore`, `get_including_deleted`, paginated `include_deleted`. |
| Modify | `tests/services/test_field_service.py` | Add cases for `_validate_parent`, circular ref, `get_tree`, `get_children`, duplicate-name pre_create. |
| Modify | `tests/services/test_field_link_service.py` | Add `bulk_create` paths + `delete` not-found. |
| Modify | `tests/services/test_dataset_schema_service.py` | Add `_pre_delete` pin block + `schema_` rename in create/update. |
| Create | `tests/services/test_lake_sync_service.py` | DB-backed lake-sync error-branch tests via `LakeSyncService`. |
| Create | `tests/repositories/test_type_instance_repository.py` | `get_by_parent_and_slot`, `get_children`, `get_tree`. |
| Modify | `CLAUDE.md` | One-line note on running scoped coverage. |

---

## Conventions reminder (read before starting)

- Tests run inside Docker: `make test-docker`. Narrow scope with `PYTEST_ARGS="-v tests/path/test_x.py" make test-docker`.
- One DB instance only — if `aide-db-test-1` is running, stop it: `docker stop aide-db-test-1`.
- DB-backed tests use the auto-applied `transactional_session` fixture — every test rolls back. Never call `await session.commit()` except inside fixtures that build auth state.
- Service tests use mocked UoW. Pattern in `tests/services/test_field_link_service.py` and `tests/services/test_auth_service.py`.
- Soft-delete-capable models need `if X is None or X.deleted_at is not None`. Setting `deleted_at` manually requires naive datetime: `datetime.now(timezone.utc).replace(tzinfo=None)`.
- Run `make format` after writing each test file (black + ruff --fix).
- Commit messages: imperative ≤50 chars. Use `caveman:caveman-commit` skill or write directly.

---

## Task 1: Refresh-token service flow

**Files:**
- Create: `tests/services/test_auth_service_refresh.py`

Targets `backend/services/auth_service.py:75-117` (refresh + revoke).

- [ ] **Step 1: Write the failing tests**

```python
# tests/services/test_auth_service_refresh.py
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models import RefreshToken, User
from backend.services.auth_service import AuthService


class _MockRefreshTokens:
    def __init__(self) -> None:
        self.get_by_token_hash = AsyncMock()
        self.create = AsyncMock()
        self.update = AsyncMock()
        self.revoke_all_for_user = AsyncMock(return_value=0)


class _MockUsers:
    def __init__(self) -> None:
        self.get_by_email = AsyncMock()
        self.get = AsyncMock()


class _MockUoW:
    def __init__(self) -> None:
        self.users = _MockUsers()
        self.refresh_tokens = _MockRefreshTokens()
        self.session = MagicMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def uow() -> _MockUoW:
    return _MockUoW()


@pytest.fixture
def service() -> AuthService:
    return AuthService()


def _user(active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email="u@example.com",
        hashed_password="x",
        is_active=active,
        row_version=1,
    )


def _token(
    *,
    user_id: uuid.UUID,
    revoked: bool = False,
    expired: bool = False,
) -> RefreshToken:
    now = datetime.now(timezone.utc)
    return RefreshToken(
        id=uuid.uuid4(),
        token_hash="hash",
        user_id=user_id,
        expires_at=(now - timedelta(days=1)) if expired else (now + timedelta(days=30)),
        revoked_at=now if revoked else None,
        client_info=None,
    )


@pytest.mark.asyncio
async def test_refresh_invalid_token(service: AuthService, uow: _MockUoW):
    uow.refresh_tokens.get_by_token_hash.return_value = None
    with pytest.raises(AppException) as exc:
        await service.refresh_access_token(uow=uow, raw_refresh_token="raw")
    assert exc.value.error_code == errors.REFRESH_TOKEN_INVALID


@pytest.mark.asyncio
async def test_refresh_revoked_token(service: AuthService, uow: _MockUoW):
    user = _user()
    uow.refresh_tokens.get_by_token_hash.return_value = _token(
        user_id=user.id, revoked=True
    )
    with pytest.raises(AppException) as exc:
        await service.refresh_access_token(uow=uow, raw_refresh_token="raw")
    assert exc.value.error_code == errors.REFRESH_TOKEN_REVOKED


@pytest.mark.asyncio
async def test_refresh_expired_token(service: AuthService, uow: _MockUoW):
    user = _user()
    uow.refresh_tokens.get_by_token_hash.return_value = _token(
        user_id=user.id, expired=True
    )
    with pytest.raises(AppException) as exc:
        await service.refresh_access_token(uow=uow, raw_refresh_token="raw")
    assert exc.value.error_code == errors.REFRESH_TOKEN_EXPIRED


@pytest.mark.asyncio
async def test_refresh_inactive_user(service: AuthService, uow: _MockUoW):
    user = _user(active=False)
    uow.refresh_tokens.get_by_token_hash.return_value = _token(user_id=user.id)
    uow.users.get.return_value = user
    with pytest.raises(AppException) as exc:
        await service.refresh_access_token(uow=uow, raw_refresh_token="raw")
    assert exc.value.error_code == errors.INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_refresh_user_missing(service: AuthService, uow: _MockUoW):
    user = _user()
    uow.refresh_tokens.get_by_token_hash.return_value = _token(user_id=user.id)
    uow.users.get.return_value = None
    with pytest.raises(AppException) as exc:
        await service.refresh_access_token(uow=uow, raw_refresh_token="raw")
    assert exc.value.error_code == errors.INVALID_CREDENTIALS


@pytest.mark.asyncio
async def test_refresh_rotates_and_returns_pair(
    service: AuthService, uow: _MockUoW
):
    user = _user()
    db_token = _token(user_id=user.id)
    uow.refresh_tokens.get_by_token_hash.return_value = db_token
    uow.users.get.return_value = user

    out = await service.refresh_access_token(uow=uow, raw_refresh_token="raw")

    assert db_token.revoked_at is not None  # old token rotated
    uow.refresh_tokens.update.assert_awaited()
    uow.refresh_tokens.create.assert_awaited()  # new token persisted
    assert out.access_token
    assert out.refresh_token
    assert out.token_type == "bearer"


@pytest.mark.asyncio
async def test_revoke_refresh_token_when_present(
    service: AuthService, uow: _MockUoW
):
    user = _user()
    db_token = _token(user_id=user.id)
    uow.refresh_tokens.get_by_token_hash.return_value = db_token
    await service.revoke_refresh_token(uow=uow, raw_refresh_token="raw")
    assert db_token.revoked_at is not None
    uow.refresh_tokens.update.assert_awaited()


@pytest.mark.asyncio
async def test_revoke_refresh_token_already_revoked_is_noop(
    service: AuthService, uow: _MockUoW
):
    user = _user()
    db_token = _token(user_id=user.id, revoked=True)
    original_revoked_at = db_token.revoked_at
    uow.refresh_tokens.get_by_token_hash.return_value = db_token
    await service.revoke_refresh_token(uow=uow, raw_refresh_token="raw")
    assert db_token.revoked_at == original_revoked_at
    uow.refresh_tokens.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_refresh_token_unknown_is_noop(
    service: AuthService, uow: _MockUoW
):
    uow.refresh_tokens.get_by_token_hash.return_value = None
    await service.revoke_refresh_token(uow=uow, raw_refresh_token="raw")
    uow.refresh_tokens.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_all_user_tokens_delegates(
    service: AuthService, uow: _MockUoW
):
    uid = uuid.uuid4()
    await service.revoke_all_user_tokens(uow=uow, user_id=uid)
    uow.refresh_tokens.revoke_all_for_user.assert_awaited_once_with(uid)


@pytest.mark.asyncio
async def test_create_tokens_for_technical_user_uses_long_ttl(
    service: AuthService, uow: _MockUoW
):
    from backend.models.user import UserType

    user = _user()
    user.user_type = UserType.TECHNICAL.value

    out = await service.create_tokens_for_user(uow, user, client_info="ci")
    uow.refresh_tokens.create.assert_awaited()
    created = uow.refresh_tokens.create.await_args.kwargs["obj_in"]
    # technical TTL > regular TTL
    assert (created.expires_at - datetime.now(timezone.utc)).days >= 1
    assert out.refresh_token
```

- [ ] **Step 2: Run tests, verify they fail**

```
PYTEST_ARGS="-v tests/services/test_auth_service_refresh.py" make test-docker
```

Expected: tests run; they should PASS already because the production code exists. The point of this task is to **lock in** behavior — no production change. If any test reports a different `error_code` or path, that's a real regression.

- [ ] **Step 3: Confirm coverage uplift**

```
PYTEST_ARGS="-v --cov=backend.services.auth_service --cov-report=term-missing tests/services/test_auth_service_refresh.py tests/services/test_auth_service.py" make test-docker
```

Expected: `backend/services/auth_service.py` coverage ≥ 95%.

- [ ] **Step 4: Format**

```
make format
```

- [ ] **Step 5: Commit**

```bash
git add tests/services/test_auth_service_refresh.py
git commit -m "test(auth): cover refresh-token flow"
```

---

## Task 2: RefreshTokenRepository DB-backed tests

**Files:**
- Create: `tests/repositories/test_refresh_token_repository.py`

Targets `backend/repositories/refresh_token.py:20-37`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/repositories/test_refresh_token_repository.py
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import get_password_hash
from backend.models import RefreshToken, User
from backend.repositories.refresh_token import RefreshTokenRepository


async def _make_user(session: AsyncSession, suffix: str) -> User:
    user = User(
        email=f"rt_{suffix}@example.com",
        hashed_password=get_password_hash("pw"),
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_get_by_token_hash_returns_match(transactional_session: AsyncSession):
    user = await _make_user(transactional_session, "byhash")
    tok = RefreshToken(
        token_hash="abc123",
        user_id=user.id,
        expires_at=_naive_now() + timedelta(days=1),
    )
    transactional_session.add(tok)
    await transactional_session.flush()

    repo = RefreshTokenRepository(transactional_session)
    found = await repo.get_by_token_hash("abc123")
    assert found is not None and found.id == tok.id


@pytest.mark.asyncio
async def test_get_by_token_hash_misses(transactional_session: AsyncSession):
    repo = RefreshTokenRepository(transactional_session)
    assert await repo.get_by_token_hash("nope") is None


@pytest.mark.asyncio
async def test_revoke_all_for_user_marks_active_only(
    transactional_session: AsyncSession,
):
    user = await _make_user(transactional_session, "rall")
    other = await _make_user(transactional_session, "rother")

    active = RefreshToken(
        token_hash="a",
        user_id=user.id,
        expires_at=_naive_now() + timedelta(days=1),
    )
    already_revoked = RefreshToken(
        token_hash="b",
        user_id=user.id,
        expires_at=_naive_now() + timedelta(days=1),
        revoked_at=_naive_now(),
    )
    other_user_token = RefreshToken(
        token_hash="c",
        user_id=other.id,
        expires_at=_naive_now() + timedelta(days=1),
    )
    transactional_session.add_all([active, already_revoked, other_user_token])
    await transactional_session.flush()

    repo = RefreshTokenRepository(transactional_session)
    count = await repo.revoke_all_for_user(user.id)

    assert count == 1
    await transactional_session.refresh(active)
    await transactional_session.refresh(other_user_token)
    assert active.revoked_at is not None
    assert other_user_token.revoked_at is None  # untouched


@pytest.mark.asyncio
async def test_revoke_all_for_user_no_active_returns_zero(
    transactional_session: AsyncSession,
):
    user = await _make_user(transactional_session, "rzero")
    repo = RefreshTokenRepository(transactional_session)
    assert await repo.revoke_all_for_user(user.id) == 0


@pytest.mark.asyncio
async def test_delete_expired_hard_deletes(transactional_session: AsyncSession):
    user = await _make_user(transactional_session, "del")
    expired = RefreshToken(
        token_hash="exp",
        user_id=user.id,
        expires_at=_naive_now() - timedelta(days=2),
    )
    fresh = RefreshToken(
        token_hash="fre",
        user_id=user.id,
        expires_at=_naive_now() + timedelta(days=2),
    )
    transactional_session.add_all([expired, fresh])
    await transactional_session.flush()

    repo = RefreshTokenRepository(transactional_session)
    count = await repo.delete_expired(_naive_now() - timedelta(days=1))

    assert count == 1
    assert await repo.get_by_token_hash("exp") is None
    assert await repo.get_by_token_hash("fre") is not None
```

- [ ] **Step 2: Run + check failures**

```
PYTEST_ARGS="-v tests/repositories/test_refresh_token_repository.py" make test-docker
```

Expected: PASS (production code already exists).

- [ ] **Step 3: Format**

```
make format
```

- [ ] **Step 4: Commit**

```bash
git add tests/repositories/test_refresh_token_repository.py
git commit -m "test(repo): cover refresh-token repository"
```

---

## Task 3: BaseRepository filter operators

**Files:**
- Create: `tests/repositories/test_base_filters.py`

Targets `backend/repositories/base.py:46-67, 71, 82` (LT/LTE/IN/LIKE branches and unknown-column errors). LIKE escape is security-relevant.

- [ ] **Step 1: Write the failing tests**

```python
# tests/repositories/test_base_filters.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.filter_sort import FilterOp, FilterSpec
from backend.models import SystemKind
from backend.repositories.system_kind import SystemKindRepository


async def _seed(session: AsyncSession) -> None:
    rows = [
        SystemKind(code="FLT_A", name="Apple"),
        SystemKind(code="FLT_B", name="Banana"),
        SystemKind(code="FLT_C", name="Cherry 50%"),
        SystemKind(code="FLT_D", name="Date"),
    ]
    session.add_all(rows)
    await session.flush()


@pytest.mark.asyncio
async def test_filter_eq(transactional_session: AsyncSession):
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    items, total = await repo.get_multi_paginated(
        filters={"code": FilterSpec(field="code", op=FilterOp.EQ, value="FLT_A")}
    )
    assert total == 1 and items[0].code == "FLT_A"


@pytest.mark.asyncio
async def test_filter_in(transactional_session: AsyncSession):
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    items, total = await repo.get_multi_paginated(
        filters={
            "code": FilterSpec(
                field="code", op=FilterOp.IN, value=["FLT_A", "FLT_C"]
            )
        }
    )
    codes = sorted(i.code for i in items)
    assert total == 2 and codes == ["FLT_A", "FLT_C"]


@pytest.mark.asyncio
async def test_filter_gt_gte_lt_lte(transactional_session: AsyncSession):
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    # GT
    _, total_gt = await repo.get_multi_paginated(
        filters={"code": FilterSpec(field="code", op=FilterOp.GT, value="FLT_B")}
    )
    assert total_gt == 2  # FLT_C, FLT_D
    # GTE
    _, total_gte = await repo.get_multi_paginated(
        filters={"code": FilterSpec(field="code", op=FilterOp.GTE, value="FLT_B")}
    )
    assert total_gte == 3
    # LT
    _, total_lt = await repo.get_multi_paginated(
        filters={"code": FilterSpec(field="code", op=FilterOp.LT, value="FLT_C")}
    )
    assert total_lt == 2  # FLT_A, FLT_B
    # LTE
    _, total_lte = await repo.get_multi_paginated(
        filters={"code": FilterSpec(field="code", op=FilterOp.LTE, value="FLT_C")}
    )
    assert total_lte == 3


@pytest.mark.asyncio
async def test_filter_like_escapes_wildcards(transactional_session: AsyncSession):
    """Raw `%` and `_` in user input must NOT act as SQL wildcards."""
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    # Only 'Cherry 50%' contains a literal '%'. A naive ILIKE without
    # escaping would match every row.
    _, total = await repo.get_multi_paginated(
        filters={"name": FilterSpec(field="name", op=FilterOp.LIKE, value="50%")}
    )
    assert total == 1


@pytest.mark.asyncio
async def test_filter_like_underscore_literal(transactional_session: AsyncSession):
    """Underscore in user input is escaped — must not act as single-char wildcard."""
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    # No row contains a literal underscore in `name`.
    _, total = await repo.get_multi_paginated(
        filters={"name": FilterSpec(field="name", op=FilterOp.LIKE, value="_")}
    )
    assert total == 0


@pytest.mark.asyncio
async def test_filter_unknown_column_raises(transactional_session: AsyncSession):
    repo = SystemKindRepository(transactional_session)
    with pytest.raises(ValueError, match="no column 'nope'"):
        await repo.get_multi_paginated(
            filters={
                "nope": FilterSpec(field="nope", op=FilterOp.EQ, value="x"),
            }
        )


@pytest.mark.asyncio
async def test_filter_plain_dict_unknown_column_raises(
    transactional_session: AsyncSession,
):
    repo = SystemKindRepository(transactional_session)
    with pytest.raises(ValueError, match="no column 'missing'"):
        await repo.get_multi_paginated(filters={"missing": "x"})


@pytest.mark.asyncio
async def test_sort_unknown_column_raises(transactional_session: AsyncSession):
    repo = SystemKindRepository(transactional_session)
    with pytest.raises(ValueError, match="no column 'nope'"):
        await repo.get_multi_paginated(sort=[("nope", False)])


@pytest.mark.asyncio
async def test_sort_desc_orders_correctly(transactional_session: AsyncSession):
    await _seed(transactional_session)
    repo = SystemKindRepository(transactional_session)
    items, _ = await repo.get_multi_paginated(
        filters={
            "code": FilterSpec(
                field="code", op=FilterOp.IN, value=["FLT_A", "FLT_B", "FLT_C"]
            )
        },
        sort=[("code", True)],
    )
    assert [i.code for i in items] == ["FLT_C", "FLT_B", "FLT_A"]
```

- [ ] **Step 2: Run + check**

```
PYTEST_ARGS="-v tests/repositories/test_base_filters.py" make test-docker
```

Expected: PASS — production code already implements escape via `replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")` (`backend/repositories/base.py:62-67`).

- [ ] **Step 3: Format + commit**

```bash
make format
git add tests/repositories/test_base_filters.py
git commit -m "test(repo): cover BaseRepository filter operators"
```

---

## Task 4: SoftDeleteRepository

**Files:**
- Create: `tests/repositories/test_soft_delete_repository.py`

Targets `backend/repositories/base.py:158-232` (`SoftDeleteRepository.restore`, `get_including_deleted`, paginated `include_deleted=True`, `delete` setting `deleted_at`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/repositories/test_soft_delete_repository.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SystemKind
from backend.repositories.system_kind import SystemKindRepository


@pytest.mark.asyncio
async def test_soft_delete_then_get_returns_none(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="SD_A", name="A")
    transactional_session.add(kind)
    await transactional_session.flush()
    repo = SystemKindRepository(transactional_session)

    await repo.delete(db_obj=kind)
    # default get filters out deleted
    assert await repo.get(kind.id) is None


@pytest.mark.asyncio
async def test_get_including_deleted_returns_row(
    transactional_session: AsyncSession,
):
    kind = SystemKind(code="SD_B", name="B")
    transactional_session.add(kind)
    await transactional_session.flush()
    repo = SystemKindRepository(transactional_session)
    await repo.delete(db_obj=kind)

    found = await repo.get_including_deleted(kind.id)
    assert found is not None
    assert found.deleted_at is not None


@pytest.mark.asyncio
async def test_restore_clears_deleted_at(transactional_session: AsyncSession):
    kind = SystemKind(code="SD_C", name="C")
    transactional_session.add(kind)
    await transactional_session.flush()
    repo = SystemKindRepository(transactional_session)
    await repo.delete(db_obj=kind)

    restored = await repo.restore(db_obj=kind)
    assert restored.deleted_at is None
    # standard get works again
    assert await repo.get(kind.id) is not None


@pytest.mark.asyncio
async def test_get_multi_excludes_deleted_by_default(
    transactional_session: AsyncSession,
):
    a = SystemKind(code="SD_D", name="D")
    b = SystemKind(code="SD_E", name="E")
    transactional_session.add_all([a, b])
    await transactional_session.flush()
    repo = SystemKindRepository(transactional_session)
    await repo.delete(db_obj=a)

    items = await repo.get_multi()
    codes = {i.code for i in items}
    assert "SD_E" in codes
    assert "SD_D" not in codes


@pytest.mark.asyncio
async def test_get_multi_paginated_include_deleted(
    transactional_session: AsyncSession,
):
    a = SystemKind(code="SD_F", name="F")
    b = SystemKind(code="SD_G", name="G")
    transactional_session.add_all([a, b])
    await transactional_session.flush()
    repo = SystemKindRepository(transactional_session)
    await repo.delete(db_obj=a)

    items, total = await repo.get_multi_paginated(include_deleted=True)
    codes = {i.code for i in items}
    assert {"SD_F", "SD_G"}.issubset(codes)
    assert total >= 2

    # without flag — only non-deleted
    items, total = await repo.get_multi_paginated(include_deleted=False)
    codes = {i.code for i in items}
    assert "SD_F" not in codes
    assert "SD_G" in codes
```

- [ ] **Step 2: Run**

```
PYTEST_ARGS="-v tests/repositories/test_soft_delete_repository.py" make test-docker
```

Expected: PASS.

- [ ] **Step 3: Format + commit**

```bash
make format
git add tests/repositories/test_soft_delete_repository.py
git commit -m "test(repo): cover soft-delete repository"
```

---

## Task 5: FieldService validation branches

**Files:**
- Modify: `tests/services/test_field_service.py` — append new tests at end of file.

Targets `backend/services/field.py:34-45, 47-62, 72-79, 133-135, 144-147` (parent / circular ref / dataset-mismatch / get_tree / get_children / pre_create duplicate-name).

- [ ] **Step 1: Append new tests**

```python
# Append to tests/services/test_field_service.py


from unittest.mock import patch
from backend.schemas.field import FieldCreate


class _MockUoWWithFields:
    def __init__(self) -> None:
        self.session = AsyncMock()
        self.datasets = AsyncMock()
        self.fields = AsyncMock()
        self.field_links = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.mark.asyncio
async def test_pre_create_dataset_missing_raises(field_service: FieldService):
    uow = _MockUoWWithFields()
    uow.datasets.get = AsyncMock(return_value=None)
    obj_in = FieldCreate(dataset_id=uuid.uuid4(), name="x", origin="mapped")

    with pytest.raises(AppException) as exc:
        with patch.object(field_service, "_get_repository"):
            await field_service.create(uow=uow, obj_in=obj_in)
    assert exc.value.error_code == errors.DATASET_NOT_FOUND


@pytest.mark.asyncio
async def test_pre_create_parent_missing_raises(field_service: FieldService):
    uow = _MockUoWWithFields()
    uow.datasets.get = AsyncMock(return_value=object())
    uow.fields.get = AsyncMock(return_value=None)
    obj_in = FieldCreate(
        dataset_id=uuid.uuid4(),
        name="x",
        origin="mapped",
        parent_id=uuid.uuid4(),
    )

    with pytest.raises(AppException) as exc:
        with patch.object(field_service, "_get_repository"):
            await field_service.create(uow=uow, obj_in=obj_in)
    assert exc.value.error_code == errors.FIELD_PARENT_NOT_FOUND


@pytest.mark.asyncio
async def test_pre_create_parent_dataset_mismatch_raises(
    field_service: FieldService,
):
    uow = _MockUoWWithFields()
    uow.datasets.get = AsyncMock(return_value=object())
    parent = _make_field()
    uow.fields.get = AsyncMock(return_value=parent)

    obj_in = FieldCreate(
        dataset_id=uuid.uuid4(),  # different from parent.dataset_id
        name="x",
        origin="mapped",
        parent_id=parent.id,
    )

    with pytest.raises(AppException) as exc:
        with patch.object(field_service, "_get_repository"):
            await field_service.create(uow=uow, obj_in=obj_in)
    assert exc.value.error_code == errors.FIELD_PARENT_DATASET_MISMATCH


@pytest.mark.asyncio
async def test_pre_create_duplicate_name_raises(field_service: FieldService):
    uow = _MockUoWWithFields()
    uow.datasets.get = AsyncMock(return_value=object())
    repo = _MockFieldRepo()
    repo.get_by_dataset_and_name.return_value = _make_field()  # collision

    obj_in = FieldCreate(dataset_id=uuid.uuid4(), name="dup", origin="mapped")
    with pytest.raises(AppException) as exc:
        with patch.object(field_service, "_get_repository", return_value=repo):
            await field_service.create(uow=uow, obj_in=obj_in)
    assert exc.value.error_code == errors.FIELD_ALREADY_EXISTS


@pytest.mark.asyncio
async def test_circular_reference_self_assigned(field_service: FieldService):
    uow = _MockUoWWithFields()
    me = _make_field()
    # new_parent_id == self.id → immediate cycle
    with pytest.raises(AppException) as exc:
        await field_service._check_circular_reference(uow, me.id, me.id)
    assert exc.value.error_code == errors.FIELD_CIRCULAR_REFERENCE


@pytest.mark.asyncio
async def test_circular_reference_via_ancestor(field_service: FieldService):
    """me -> child -> grandchild; assigning me.parent = grandchild forms a cycle."""
    uow = _MockUoWWithFields()
    me = _make_field()
    child = _make_field()
    grandchild = _make_field()
    child.parent_id = me.id
    grandchild.parent_id = child.id

    async def fake_get(field_id):
        if field_id == grandchild.id:
            return grandchild
        if field_id == child.id:
            return child
        if field_id == me.id:
            return me
        return None

    uow.fields.get = AsyncMock(side_effect=fake_get)
    with pytest.raises(AppException) as exc:
        await field_service._check_circular_reference(uow, me.id, grandchild.id)
    assert exc.value.error_code == errors.FIELD_CIRCULAR_REFERENCE


@pytest.mark.asyncio
async def test_circular_reference_breaks_on_visited_loop(
    field_service: FieldService,
):
    """If the chain itself loops on a non-self id, walker terminates without raising."""
    uow = _MockUoWWithFields()
    me = _make_field()
    a = _make_field()
    b = _make_field()
    a.parent_id = b.id
    b.parent_id = a.id  # a<->b loop, neither is `me`

    async def fake_get(field_id):
        if field_id == a.id:
            return a
        if field_id == b.id:
            return b
        return None

    uow.fields.get = AsyncMock(side_effect=fake_get)
    # Should NOT raise — `me` is not in the cycle.
    await field_service._check_circular_reference(uow, me.id, a.id)


@pytest.mark.asyncio
async def test_get_tree_validates_dataset(field_service: FieldService):
    uow = _MockUoWWithFields()
    uow.datasets.get = AsyncMock(return_value=None)
    with pytest.raises(AppException) as exc:
        await field_service.get_tree(uow, uuid.uuid4())
    assert exc.value.error_code == errors.DATASET_NOT_FOUND


@pytest.mark.asyncio
async def test_get_children_field_missing(field_service: FieldService):
    uow = _MockUoWWithFields()
    uow.fields.get = AsyncMock(return_value=None)
    with pytest.raises(AppException) as exc:
        await field_service.get_children(uow, uuid.uuid4())
    assert exc.value.error_code == errors.FIELD_NOT_FOUND
```

- [ ] **Step 2: Run**

```
PYTEST_ARGS="-v tests/services/test_field_service.py" make test-docker
```

Expected: PASS.

- [ ] **Step 3: Format + commit**

```bash
make format
git add tests/services/test_field_service.py
git commit -m "test(field): cover validation + circular ref branches"
```

---

## Task 6: FieldLinkService bulk_create + delete

**Files:**
- Modify: `tests/services/test_field_link_service.py` — append new tests.

Targets `backend/services/field_link.py:81, 86-107` (`delete` not-found, `bulk_create` empty + happy + error).

- [ ] **Step 1: Append new tests**

```python
# Append to tests/services/test_field_link_service.py


from backend.models.field_link import FieldLink as FieldLinkModel


@pytest.mark.asyncio
async def test_delete_not_found_raises(service: FieldLinkService):
    uow = _MockUoW()
    repo = _MockRepo()
    repo.get.return_value = None

    with pytest.raises(AppException) as exc:
        with patch.object(service, "_get_repository", return_value=repo):
            await service.delete(uow=uow, obj_id=uuid.uuid4())
    assert exc.value.error_code == errors.FIELD_LINK_NOT_FOUND


@pytest.mark.asyncio
async def test_bulk_create_empty_returns_empty(service: FieldLinkService):
    uow = _MockUoW()
    out = await service.bulk_create(uow=uow, items=[])
    assert out == []


@pytest.mark.asyncio
async def test_bulk_create_happy_path(service: FieldLinkService):
    src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
    link = _link(src_id, tgt_id)
    sf, tf = _field(src_id), _field(tgt_id)

    uow = _MockUoW()
    uow.dataset_links.get = AsyncMock(return_value=link)
    # source then target lookup
    uow.fields.get = AsyncMock(side_effect=[sf, tf])
    uow.field_bindings.get_by_field_and_schema = AsyncMock(
        side_effect=[
            _binding(sf.id, link.source_schema_id),
            _binding(tf.id, link.target_schema_id),
        ]
    )

    repo = _MockRepo()
    created_obj = FieldLinkModel(
        id=uuid.uuid4(),
        dataset_link_id=link.id,
        source_field_id=sf.id,
        target_field_id=tf.id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        row_version=1,
    )
    repo.create_many = AsyncMock(return_value=[created_obj])

    item = FieldLinkCreate(
        dataset_link_id=link.id,
        source_field_id=sf.id,
        target_field_id=tf.id,
    )

    with patch.object(service, "_get_repository", return_value=repo):
        out = await service.bulk_create(uow=uow, items=[item], creator_id=uuid.uuid4())
    assert len(out) == 1


@pytest.mark.asyncio
async def test_bulk_create_target_origin_not_mapped_raises(
    service: FieldLinkService,
):
    src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
    link = _link(src_id, tgt_id)
    sf = _field(src_id)
    tf = _field(tgt_id, origin="tech")

    uow = _MockUoW()
    uow.dataset_links.get = AsyncMock(return_value=link)
    uow.fields.get = AsyncMock(side_effect=[sf, tf])

    item = FieldLinkCreate(
        dataset_link_id=link.id,
        source_field_id=sf.id,
        target_field_id=tf.id,
    )
    with pytest.raises(AppException) as exc:
        with patch.object(service, "_get_repository", return_value=_MockRepo()):
            await service.bulk_create(uow=uow, items=[item])
    assert exc.value.error_code == errors.FIELD_ORIGIN_CONFLICT


@pytest.mark.asyncio
async def test_bulk_create_dataset_link_missing(service: FieldLinkService):
    uow = _MockUoW()
    uow.dataset_links.get = AsyncMock(return_value=None)
    item = FieldLinkCreate(
        dataset_link_id=uuid.uuid4(),
        source_field_id=uuid.uuid4(),
        target_field_id=uuid.uuid4(),
    )
    with pytest.raises(AppException) as exc:
        with patch.object(service, "_get_repository", return_value=_MockRepo()):
            await service.bulk_create(uow=uow, items=[item])
    assert exc.value.error_code == errors.DATASET_LINK_NOT_FOUND


@pytest.mark.asyncio
async def test_bulk_create_source_dataset_mismatch(service: FieldLinkService):
    src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
    link = _link(src_id, tgt_id)
    sf_wrong = _field(uuid.uuid4())  # not in link.source_dataset_id
    tf = _field(tgt_id)

    uow = _MockUoW()
    uow.dataset_links.get = AsyncMock(return_value=link)
    uow.fields.get = AsyncMock(side_effect=[sf_wrong, tf])

    item = FieldLinkCreate(
        dataset_link_id=link.id,
        source_field_id=sf_wrong.id,
        target_field_id=tf.id,
    )
    with pytest.raises(AppException) as exc:
        with patch.object(service, "_get_repository", return_value=_MockRepo()):
            await service.bulk_create(uow=uow, items=[item])
    assert exc.value.error_code == errors.FIELD_LINK_SOURCE_DATASET_MISMATCH


@pytest.mark.asyncio
async def test_bulk_create_target_occupied(service: FieldLinkService):
    src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
    link = _link(src_id, tgt_id)
    sf, tf = _field(src_id), _field(tgt_id)

    uow = _MockUoW()
    uow.dataset_links.get = AsyncMock(return_value=link)
    uow.fields.get = AsyncMock(side_effect=[sf, tf])
    uow.field_bindings.get_by_field_and_schema = AsyncMock(
        side_effect=[
            _binding(sf.id, link.source_schema_id),
            _binding(tf.id, link.target_schema_id),
        ]
    )

    repo = _MockRepo()
    repo.get_by_target_in_link = AsyncMock(return_value=object())  # occupied

    item = FieldLinkCreate(
        dataset_link_id=link.id,
        source_field_id=sf.id,
        target_field_id=tf.id,
    )
    with pytest.raises(AppException) as exc:
        with patch.object(service, "_get_repository", return_value=repo):
            await service.bulk_create(uow=uow, items=[item])
    assert exc.value.error_code == errors.FIELD_LINK_TARGET_OCCUPIED
```

- [ ] **Step 2: Run + format + commit**

```
PYTEST_ARGS="-v tests/services/test_field_link_service.py" make test-docker
make format
git add tests/services/test_field_link_service.py
git commit -m "test(field-link): cover bulk_create + delete branches"
```

---

## Task 7: DatasetSchemaService delete pin + schema_ rename

**Files:**
- Modify: `tests/services/test_dataset_schema_service.py` — append new tests.

Targets `backend/services/dataset_schema.py:42, 87-88, 110-111, 115-159` (`_pre_delete` blocking, schema_ rename in create + update).

- [ ] **Step 1: Read existing file to confirm fixtures**

```
Read tests/services/test_dataset_schema_service.py
```

- [ ] **Step 2: Append new DB-backed tests** (the existing file's pattern dictates whether to use mocks; use DB-backed if existing tests use `transactional_session`, else inline mocks. Append the variant that matches.)

```python
# Append to tests/services/test_dataset_schema_service.py


import pytest
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.schemas.dataset_schema import DatasetSchemaCreate, DatasetSchemaUpdate
from backend.services.dataset_schema import DatasetSchemaService


async def _seed_dataset_schema(session: AsyncSession, suffix: str):
    kind = SystemKind(code=f"DS_{suffix}", name=f"DS {suffix}")
    flavor = SystemFlavor(
        code=f"FL_{suffix}", name=f"Flavor {suffix}", kind=kind
    )
    sys = System(code=f"SYS_{suffix}", name=f"Sys {suffix}", flavor=flavor)
    session.add_all([kind, flavor, sys])
    await session.flush()
    ds = DatasetRdbms(
        kind="rdbms",
        system_id=sys.id,
        object_name=f"o_{suffix}",
        schema_name="public",
        table_name=f"t_{suffix}",
    )
    session.add(ds)
    await session.flush()
    schema = DatasetSchema(dataset_id=ds.id, version_num=1)
    session.add(schema)
    await session.flush()
    return ds, schema


@pytest.mark.asyncio
async def test_delete_blocked_when_pinned_by_dataset_link(
    transactional_session: AsyncSession,
):
    src_ds, src_schema = await _seed_dataset_schema(transactional_session, "PIN1")
    tgt_ds, tgt_schema = await _seed_dataset_schema(transactional_session, "PIN2")
    link = DatasetLink(
        source_dataset_id=src_ds.id,
        target_dataset_id=tgt_ds.id,
        source_schema_id=src_schema.id,
        target_schema_id=tgt_schema.id,
    )
    transactional_session.add(link)
    await transactional_session.flush()

    service = DatasetSchemaService()
    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session

    with pytest.raises(AppException) as exc:
        await service.delete(uow=uow, obj_id=src_schema.id)
    assert exc.value.error_code == errors.DATASET_SCHEMA_IN_USE


@pytest.mark.asyncio
async def test_delete_allowed_when_no_active_link(
    transactional_session: AsyncSession,
):
    _, schema = await _seed_dataset_schema(transactional_session, "FREE")
    service = DatasetSchemaService()
    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session

    out = await service.delete(uow=uow, obj_id=schema.id)
    assert out.id == schema.id


@pytest.mark.asyncio
async def test_delete_not_found_raises(transactional_session: AsyncSession):
    service = DatasetSchemaService()
    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session

    with pytest.raises(AppException) as exc:
        await service.delete(uow=uow, obj_id=uuid.uuid4())
    assert exc.value.error_code == errors.DATASET_SCHEMA_NOT_FOUND


@pytest.mark.asyncio
async def test_create_renames_schema_underscore_to_schema(
    transactional_session: AsyncSession,
):
    """Pydantic alias `schema_` (avoiding BaseModel.schema clash) maps to model col `schema`."""
    ds, _ = await _seed_dataset_schema(transactional_session, "SCH")
    service = DatasetSchemaService()
    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session

    payload = DatasetSchemaCreate(
        dataset_id=ds.id,
        version_num=2,
        schema_={"columns": [{"name": "id"}]},
    )
    created = await service.create(uow=uow, obj_in=payload)

    db_obj = await transactional_session.get(DatasetSchema, created.id)
    assert db_obj.schema == {"columns": [{"name": "id"}]}


@pytest.mark.asyncio
async def test_update_renames_schema_underscore_to_schema(
    transactional_session: AsyncSession,
):
    _, schema = await _seed_dataset_schema(transactional_session, "UPD")
    service = DatasetSchemaService()
    uow = UnitOfWork()
    uow.session_factory = lambda: transactional_session

    payload = DatasetSchemaUpdate(
        schema_={"columns": [{"name": "ts"}]}, row_version=schema.row_version
    )
    await service.update(uow=uow, obj_id=schema.id, obj_in=payload)

    await transactional_session.refresh(schema)
    assert schema.schema == {"columns": [{"name": "ts"}]}
```

- [ ] **Step 3: Run + format + commit**

```
PYTEST_ARGS="-v tests/services/test_dataset_schema_service.py" make test-docker
make format
git add tests/services/test_dataset_schema_service.py
git commit -m "test(schema): cover pre_delete pin + schema_ rename"
```

---

## Task 8: LakeSyncService error branches

**Files:**
- Create: `tests/services/test_lake_sync_service.py`

Targets `backend/services/lake_sync.py:65-110` and `:235-309` — error branches not exercised by API happy-path tests.

- [ ] **Step 1: Write the failing tests**

```python
# tests/services/test_lake_sync_service.py
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide_schemas.lake_sync import LakeSyncRequest
from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_schema import DatasetSchema
from backend.models.system import System
from backend.models.system_flavor import SystemFlavor
from backend.models.tech_field_template import (
    TechFieldTemplate,
    TechFieldTemplateField,
)
from backend.scripts._seed_cast_rules_core import (
    seed_from_file as seed_casts_from_file,
)
from backend.scripts._seed_core import seed_from_file as seed_dt_from_file
from backend.services.lake_sync import LakeSyncService

# Re-use API-test helpers via direct import (kept inline per CLAUDE.md guidance —
# promote to tests/_helpers.py if a 3rd copy is needed).
from tests.api.test_lake_sync import (
    _create_lake_system,
    _create_pg_system,
    _make_source_dataset,
    _seed_pg_and_iceberg,
)


def _uow_for(session: AsyncSession) -> UnitOfWork:
    uow = UnitOfWork()
    uow.session_factory = lambda: session
    return uow


def _request(target_system_id: uuid.UUID, **overrides):
    base = {
        "target_system_id": target_system_id,
        "target_layer": "core",
        "db_name": "lake",
        "table_name": "users",
        "catalog_uri": "thrift://hms:9083",
    }
    base.update(overrides)
    return LakeSyncRequest(**base)


@pytest.mark.asyncio
async def test_source_dataset_not_found(transactional_session: AsyncSession):
    await _seed_pg_and_iceberg(transactional_session)
    lake = await _create_lake_system(transactional_session)
    service = LakeSyncService()

    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=uuid.uuid4(),
            request=_request(lake.id),
            applier_id=None,
        )
    assert exc.value.error_code == errors.DATASET_NOT_FOUND


@pytest.mark.asyncio
async def test_no_source_schema_with_bindings(
    transactional_session: AsyncSession,
):
    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    lake = await _create_lake_system(transactional_session)
    # Build dataset with schema but no FieldBindings.
    ds = DatasetRdbms(
        kind="rdbms",
        system_id=pg.id,
        object_name="empty",
        schema_name="public",
        table_name="empty",
    )
    transactional_session.add(ds)
    await transactional_session.flush()
    schema = DatasetSchema(dataset_id=ds.id, version_num=1)
    transactional_session.add(schema)
    await transactional_session.flush()

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(lake.id),
            applier_id=None,
        )
    assert exc.value.error_code == errors.LAKE_SYNC_NO_SOURCE_SCHEMA


@pytest.mark.asyncio
async def test_target_system_not_found(transactional_session: AsyncSession):
    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, pg)

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(uuid.uuid4()),  # bogus target system id
            applier_id=None,
        )
    assert exc.value.error_code == errors.SYSTEM_NOT_FOUND


@pytest.mark.asyncio
async def test_tech_template_not_found(transactional_session: AsyncSession):
    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    lake = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, pg)

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(lake.id, tech_template_id=uuid.uuid4()),
            applier_id=None,
        )
    assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_NOT_FOUND


@pytest.mark.asyncio
async def test_tech_template_layer_mismatch(transactional_session: AsyncSession):
    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    lake = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, pg)

    tpl = TechFieldTemplate(
        code=f"raw_only_{uuid.uuid4().hex[:6]}",
        name="raw layer template",
        layer="raw",  # request asks for `core`
    )
    transactional_session.add(tpl)
    await transactional_session.flush()

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(lake.id, tech_template_id=tpl.id),
            applier_id=None,
        )
    assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_LAYER_MISMATCH


@pytest.mark.asyncio
async def test_tech_type_code_not_resolvable(transactional_session: AsyncSession):
    """Tech template field with an unknown type_code → TECH_TYPE_CODE_NOT_RESOLVABLE."""
    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    lake = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, pg)

    tpl = TechFieldTemplate(
        code=f"bad_{uuid.uuid4().hex[:6]}",
        name="bad tech",
        layer="core",
    )
    transactional_session.add(tpl)
    await transactional_session.flush()
    transactional_session.add(
        TechFieldTemplateField(
            template_id=tpl.id,
            name="bogus",
            type_code="DEFINITELY_NOT_A_REAL_TYPE",
            order=0,
        )
    )
    await transactional_session.flush()

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(lake.id, tech_template_id=tpl.id),
            applier_id=None,
        )
    assert exc.value.error_code == errors.TECH_TYPE_CODE_NOT_RESOLVABLE


@pytest.mark.asyncio
async def test_soft_deleted_source_dataset_rejected(
    transactional_session: AsyncSession,
):
    from datetime import datetime, timezone

    await _seed_pg_and_iceberg(transactional_session)
    pg = await _create_pg_system(transactional_session)
    lake = await _create_lake_system(transactional_session)
    ds, _, _ = await _make_source_dataset(transactional_session, pg)

    # Naive datetime — asyncpg rejects aware datetimes for TIMESTAMP WITHOUT TZ.
    ds.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await transactional_session.flush()

    service = LakeSyncService()
    with pytest.raises(AppException) as exc:
        await service.create_lake_target(
            uow=_uow_for(transactional_session),
            source_dataset_id=ds.id,
            request=_request(lake.id),
            applier_id=None,
        )
    assert exc.value.error_code == errors.DATASET_NOT_FOUND
```

- [ ] **Step 2: Run**

```
PYTEST_ARGS="-v tests/services/test_lake_sync_service.py" make test-docker
```

Expected: PASS.

- [ ] **Step 3: Format + commit**

```bash
make format
git add tests/services/test_lake_sync_service.py
git commit -m "test(lake-sync): cover service error branches"
```

---

## Task 9: TypeInstanceRepository

**Files:**
- Create: `tests/repositories/test_type_instance_repository.py`

Targets `backend/repositories/type_instance.py:14-46` (`get_by_parent_and_slot`, `get_children`, `get_tree` recursive eager load).

- [ ] **Step 1: Write the failing tests**

```python
# tests/repositories/test_type_instance_repository.py
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.data_type import DataType
from backend.models.type_instance import TypeInstance
from backend.repositories.type_instance import TypeInstanceRepository


async def _seed_two_types(session: AsyncSession, suffix: str):
    kind = SystemKind(code=f"K_{suffix}", name=f"K {suffix}")
    flavor = SystemFlavor(
        code=f"F_{suffix}", name=f"F {suffix}", kind=kind, versions=["1"]
    )
    session.add_all([kind, flavor])
    await session.flush()
    array_dt = DataType(
        system_flavor_id=flavor.id,
        code=f"array_{suffix}",
        params_schema={},
        kind="aggregate",
    )
    int_dt = DataType(
        system_flavor_id=flavor.id,
        code=f"int_{suffix}",
        params_schema={},
        kind="primitive",
    )
    session.add_all([array_dt, int_dt])
    await session.flush()
    return array_dt, int_dt


@pytest.mark.asyncio
async def test_get_by_parent_and_slot_match(transactional_session: AsyncSession):
    arr, leaf = await _seed_two_types(transactional_session, "PS1")
    parent = TypeInstance(data_type_id=arr.id, type_params=None, slot=None)
    transactional_session.add(parent)
    await transactional_session.flush()
    child = TypeInstance(
        data_type_id=leaf.id, type_params=None, slot="item", parent_id=parent.id
    )
    transactional_session.add(child)
    await transactional_session.flush()

    repo = TypeInstanceRepository(transactional_session)
    found = await repo.get_by_parent_and_slot(parent.id, "item")
    assert found is not None and found.id == child.id


@pytest.mark.asyncio
async def test_get_by_parent_and_slot_miss(transactional_session: AsyncSession):
    repo = TypeInstanceRepository(transactional_session)
    assert await repo.get_by_parent_and_slot(uuid.uuid4(), "nope") is None


@pytest.mark.asyncio
async def test_get_children_returns_all(transactional_session: AsyncSession):
    arr, leaf = await _seed_two_types(transactional_session, "GC1")
    parent = TypeInstance(data_type_id=arr.id, type_params=None, slot=None)
    transactional_session.add(parent)
    await transactional_session.flush()
    a = TypeInstance(
        data_type_id=leaf.id, type_params=None, slot="x", parent_id=parent.id
    )
    b = TypeInstance(
        data_type_id=leaf.id, type_params=None, slot="y", parent_id=parent.id
    )
    transactional_session.add_all([a, b])
    await transactional_session.flush()

    repo = TypeInstanceRepository(transactional_session)
    kids = await repo.get_children(parent.id)
    assert {c.id for c in kids} == {a.id, b.id}


@pytest.mark.asyncio
async def test_get_children_empty(transactional_session: AsyncSession):
    arr, _ = await _seed_two_types(transactional_session, "GC2")
    parent = TypeInstance(data_type_id=arr.id, type_params=None, slot=None)
    transactional_session.add(parent)
    await transactional_session.flush()

    repo = TypeInstanceRepository(transactional_session)
    assert list(await repo.get_children(parent.id)) == []


@pytest.mark.asyncio
async def test_get_tree_eager_loads_recursive_children(
    transactional_session: AsyncSession,
):
    arr, leaf = await _seed_two_types(transactional_session, "TR1")
    root = TypeInstance(data_type_id=arr.id, type_params=None, slot=None)
    transactional_session.add(root)
    await transactional_session.flush()
    mid = TypeInstance(
        data_type_id=arr.id, type_params=None, slot="item", parent_id=root.id
    )
    transactional_session.add(mid)
    await transactional_session.flush()
    leaf_ti = TypeInstance(
        data_type_id=leaf.id, type_params=None, slot="item", parent_id=mid.id
    )
    transactional_session.add(leaf_ti)
    await transactional_session.flush()

    repo = TypeInstanceRepository(transactional_session)
    tree = await repo.get_tree(root.id)

    assert tree is not None
    # Recursive eager load should not raise MissingGreenlet on traversal.
    assert len(tree.children) == 1
    assert tree.children[0].id == mid.id
    assert len(tree.children[0].children) == 1
    assert tree.children[0].children[0].id == leaf_ti.id


@pytest.mark.asyncio
async def test_get_tree_unknown_id_returns_none(transactional_session: AsyncSession):
    repo = TypeInstanceRepository(transactional_session)
    assert await repo.get_tree(uuid.uuid4()) is None
```

- [ ] **Step 2: Run + format + commit**

```
PYTEST_ARGS="-v tests/repositories/test_type_instance_repository.py" make test-docker
make format
git add tests/repositories/test_type_instance_repository.py
git commit -m "test(repo): cover type-instance repository"
```

---

## Task 10: Final coverage verification + CLAUDE.md note

**Files:**
- Modify: `CLAUDE.md` — append one bullet under `### Testing`.

- [ ] **Step 1: Run full coverage**

```
PYTEST_ARGS="-v --cov=backend --cov-report=term tests/" make test-docker
```

Expected: total coverage ≥ **91%** (was 87% baseline). Modules below should hit:

| Module | Target |
|--------|--------|
| `services/auth_service.py` | ≥ 95% |
| `services/lake_sync.py` | ≥ 75% |
| `repositories/base.py` | ≥ 90% |
| `services/field.py` | ≥ 90% |
| `services/dataset_schema.py` | ≥ 95% |
| `services/field_link.py` | ≥ 95% |
| `repositories/refresh_token.py` | 100% |
| `repositories/type_instance.py` | 100% |

If a module is below target, identify the unreached lines from `--cov-report=term-missing` and add a focused test to the corresponding task's file. Do not add tests for `__repr__` strings or trivial `Mapped[...]` declarations.

- [ ] **Step 2: Append CLAUDE.md note under `### Testing`**

```markdown
Scope a coverage run: `PYTEST_ARGS="--cov=backend.services.X --cov-report=term-missing tests/services/test_X.py" make test-docker`. Use this when writing new tests to verify branch coverage.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): note scoped coverage command"
```

---

## Self-Review

**1. Spec coverage:**

| Asked-for area | Task |
|----------------|------|
| Identify gaps | "Coverage baseline" + "File map" sections |
| Close critical (auth security) | Tasks 1, 2 |
| Close critical (generic infra) | Tasks 3, 4 |
| Close critical (services with low cov) | Tasks 5, 6, 7, 8 |
| Close critical (repositories with low cov) | Tasks 2, 9 |
| Verification | Task 10 |

**2. Placeholder scan:** None — every test step contains executable Python; every command shown verbatim.

**3. Type consistency:**
- `_MockUoW`, `_MockRepo`, `_MockFieldRepo` reused with consistent attributes per file.
- `LakeSyncRequest` constructed via dict-then-`**base` to match schema's actual fields (`target_system_id`, `target_layer`, `db_name`, `table_name`, `catalog_uri`).
- `_make_field()` and `_field()` helpers come from each test module's existing fixtures, not invented.
- `tests.api.test_lake_sync` helper imports (`_seed_pg_and_iceberg`, etc.) match function names verified in the file.

Caveat: Task 7 instructs the implementer to read the existing `test_dataset_schema_service.py` first and pick mocks-vs-DB based on the file's existing pattern. Append-style instructions account for both shapes.

**Edge case to watch:** Task 1 + Task 6 import patterns assume `_MockUoW`/`_MockRepo` already exist in the target file (they do — verified via Read). If that file is later refactored, tests need updating in lockstep.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-28-test-coverage-gaps.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration
**2. Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints

Which approach?
