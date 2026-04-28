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
