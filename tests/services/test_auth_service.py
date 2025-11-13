import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models import User
from backend.services.auth_service import AuthService


class _MockUsers:
    def __init__(self) -> None:
        self.get_by_email: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.users = _MockUsers()
        self.session = MagicMock()
        self.session.expunge = MagicMock()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    """Fixture for a mocked UnitOfWork."""
    return _MockUnitOfWork()


@pytest.fixture
def auth_service() -> AuthService:
    """Fixture for an AuthService instance."""
    return AuthService()


@pytest.fixture
def db_user() -> User:
    """Fixture for a database User model object."""
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password="hashed_password_string",
        is_active=True,
    )


@pytest.mark.asyncio
class TestAuthService:
    @patch("backend.services.auth_service.verify_password", return_value=True)
    async def test_authenticate_user_success(
        self,
        mock_verify_password: MagicMock,
        auth_service: AuthService,
        mock_uow: _MockUnitOfWork,
        db_user: User,
    ):
        """Test successful user authentication."""
        mock_uow.users.get_by_email.return_value = db_user

        result = await auth_service.authenticate_user(
            uow=mock_uow, email="test@example.com", password="password123"
        )

        mock_uow.users.get_by_email.assert_awaited_once_with(email="test@example.com")
        mock_verify_password.assert_called_once_with(
            "password123", db_user.hashed_password
        )
        mock_uow.session.expunge.assert_called_once_with(db_user)
        assert result == db_user

    @patch("backend.services.auth_service.verify_password", return_value=False)
    async def test_authenticate_user_wrong_password(
        self,
        mock_verify_password: MagicMock,
        auth_service: AuthService,
        mock_uow: _MockUnitOfWork,
        db_user: User,
    ):
        """Test authentication with a wrong password."""
        mock_uow.users.get_by_email.return_value = db_user

        with pytest.raises(AppException) as exc_info:
            await auth_service.authenticate_user(
                uow=mock_uow, email="test@example.com", password="wrong_password"
            )

        assert exc_info.value.error_code == errors.INVALID_CREDENTIALS
        mock_uow.session.expunge.assert_not_called()

    async def test_authenticate_user_not_found(
        self, auth_service: AuthService, mock_uow: _MockUnitOfWork
    ):
        """Test authentication for a non-existent user."""
        mock_uow.users.get_by_email.return_value = None

        with pytest.raises(AppException) as exc_info:
            await auth_service.authenticate_user(
                uow=mock_uow, email="not.found@example.com", password="any_password"
            )

        assert exc_info.value.error_code == errors.INVALID_CREDENTIALS
        mock_uow.session.expunge.assert_not_called()
