import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

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
async def test_refresh_rotates_and_returns_pair(service: AuthService, uow: _MockUoW):
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
async def test_revoke_refresh_token_when_present(service: AuthService, uow: _MockUoW):
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
async def test_revoke_all_user_tokens_delegates(service: AuthService, uow: _MockUoW):
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
