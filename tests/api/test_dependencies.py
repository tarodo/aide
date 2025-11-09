import uuid
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.api.dependencies import get_current_user, get_current_superuser
from backend.core.security import create_access_token
from backend.db.uow import UnitOfWork
from backend.models import User


class _MockUsers:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.users = _MockUsers()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    """Fixture for a mocked UnitOfWork."""
    return _MockUnitOfWork()


@pytest.fixture
def active_user() -> User:
    """Fixture for a sample active User object."""
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        is_active=True,
        is_superuser=False,
    )


@pytest.fixture
def inactive_user() -> User:
    """Fixture for a sample inactive User object."""
    return User(
        id=uuid.uuid4(),
        email="inactive@example.com",
        is_active=False,
        is_superuser=False,
    )


@pytest.fixture
def superuser() -> User:
    """Fixture for a sample superuser object."""
    return User(
        id=uuid.uuid4(),
        email="admin@example.com",
        is_active=True,
        is_superuser=True,
    )


@pytest.mark.asyncio
class TestGetCurrentUser:
    async def test_get_current_user_success(
        self, mock_uow: _MockUnitOfWork, active_user: User
    ):
        """Test successful retrieval of the current user."""
        # Arrange
        mock_uow.users.get.return_value = active_user
        token = create_access_token(data={"user_id": str(active_user.id)})

        # Act
        result = await get_current_user(token=token, uow=cast(UnitOfWork, mock_uow))

        # Assert
        assert result == active_user
        mock_uow.users.get.assert_awaited_once_with(active_user.id)

    async def test_get_current_user_invalid_token(self, mock_uow: _MockUnitOfWork):
        """Test dependency with an invalid token string."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                token="invalid.token.string", uow=cast(UnitOfWork, mock_uow)
            )
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Could not validate credentials"

    async def test_get_current_user_no_user_id(self, mock_uow: _MockUnitOfWork):
        """Test dependency with a token missing the user_id."""
        token = create_access_token(data={"sub": "some_subject"})
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token, uow=cast(UnitOfWork, mock_uow))
        assert exc_info.value.status_code == 401

    async def test_get_current_user_user_not_found(self, mock_uow: _MockUnitOfWork):
        """Test dependency when user_id from token does not exist in DB."""
        mock_uow.users.get.return_value = None
        user_id = uuid.uuid4()
        token = create_access_token(data={"user_id": str(user_id)})

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token, uow=cast(UnitOfWork, mock_uow))
        assert exc_info.value.status_code == 401
        mock_uow.users.get.assert_awaited_once_with(user_id)

    async def test_get_current_user_inactive(
        self, mock_uow: _MockUnitOfWork, inactive_user: User
    ):
        """Test dependency when the user found is inactive."""
        mock_uow.users.get.return_value = inactive_user
        token = create_access_token(data={"user_id": str(inactive_user.id)})

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token, uow=cast(UnitOfWork, mock_uow))
        assert exc_info.value.status_code == 401
        mock_uow.users.get.assert_awaited_once_with(inactive_user.id)


@pytest.mark.asyncio
class TestGetCurrentSuperuser:
    async def test_get_current_superuser_success(self, superuser: User):
        """Test successful retrieval of a superuser."""
        result = await get_current_superuser(current_user=superuser)
        assert result == superuser

    async def test_get_current_superuser_not_a_superuser(self, active_user: User):
        """Test dependency when the user is not a superuser."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_superuser(current_user=active_user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "The user doesn't have enough privileges"
