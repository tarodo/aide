import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import User
from backend.schemas.user import UserCreate, UserRead
from backend.services.user import UserService
from backend.services.exceptions import UserAlreadyExistsError, UserNotFoundError


class _MockUsers:
    def __init__(self) -> None:
        self.get_by_email: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()
        self.create: AsyncMock = AsyncMock()


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
def user_service() -> UserService:
    """Fixture for a UserService instance."""
    return UserService()


@pytest.fixture
def user_create_schema() -> UserCreate:
    """Fixture for a UserCreate schema object."""
    return UserCreate(
        email="test@example.com", password="password123", full_name="Test User"
    )


@pytest.fixture
def db_user() -> User:
    """Fixture for a database User model object."""
    user_id = uuid.uuid4()
    return User(
        id=user_id,
        email="test@example.com",
        full_name="Test User",
        hashed_password="hashed_password_string",
        is_active=True,
        is_superuser=False,
        created_by=user_id,
        updated_by=user_id,
    )


@pytest.mark.asyncio
@patch("backend.services.user.get_password_hash", return_value="hashed_password_string")
async def test_create_user_success(
    mock_get_password_hash: MagicMock,
    user_service: UserService,
    mock_uow: AsyncMock,
    user_create_schema: UserCreate,
    db_user: User,
):
    """Test successful user creation."""
    # Arrange
    mock_uow.users.get_by_email.return_value = None
    mock_uow.users.create.return_value = db_user

    # Act
    result = await user_service.create_user(uow=mock_uow, user_in=user_create_schema)

    # Assert
    mock_uow.users.get_by_email.assert_awaited_once_with(user_create_schema.email)
    mock_get_password_hash.assert_called_once_with(user_create_schema.password)
    mock_uow.users.create.assert_awaited_once()
    created_user_arg = mock_uow.users.create.call_args.kwargs["obj_in"]
    assert created_user_arg.email == user_create_schema.email
    assert created_user_arg.hashed_password == "hashed_password_string"
    assert isinstance(result, UserRead)
    assert result.email == db_user.email
    assert result.id == db_user.id


@pytest.mark.asyncio
async def test_create_user_duplicate_email(
    user_service: UserService,
    mock_uow: AsyncMock,
    user_create_schema: UserCreate,
    db_user: User,
):
    """Test user creation with a duplicate email."""
    # Arrange
    mock_uow.users.get_by_email.return_value = db_user

    # Act & Assert
    with pytest.raises(UserAlreadyExistsError):
        await user_service.create_user(uow=mock_uow, user_in=user_create_schema)

    mock_uow.users.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_user_success(
    user_service: UserService, mock_uow: AsyncMock, db_user: User
):
    """Test getting an existing user by ID."""
    mock_uow.users.get.return_value = db_user
    result = await user_service.get_user(uow=mock_uow, user_id=db_user.id)
    assert isinstance(result, UserRead)
    assert result.id == db_user.id
    mock_uow.users.get.assert_awaited_once_with(db_user.id)


@pytest.mark.asyncio
async def test_get_user_not_found(user_service: UserService, mock_uow: AsyncMock):
    """Test getting a non-existent user by ID."""
    mock_uow.users.get.return_value = None
    user_id = uuid.uuid4()

    with pytest.raises(UserNotFoundError):
        await user_service.get_user(uow=mock_uow, user_id=user_id)

    mock_uow.users.get.assert_awaited_once_with(user_id)
