import uuid
from datetime import UTC, datetime
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
        self.update: AsyncMock = AsyncMock()


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
    now = datetime.now(UTC)
    return User(
        id=user_id,
        email="test@example.com",
        full_name="Test User",
        hashed_password="hashed_password_string",
        is_active=True,
        is_superuser=False,
        created_by=user_id,
        updated_by=user_id,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def db_superuser() -> User:
    """Fixture for a superuser model object."""
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    return User(
        id=user_id,
        email="admin@example.com",
        full_name="Admin User",
        hashed_password="hashed_password_string",
        is_active=True,
        is_superuser=True,
        created_by=user_id,
        updated_by=user_id,
        created_at=now,
        updated_at=now,
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
    creator_id = uuid.uuid4()

    # Act
    result = await user_service.create_user(
        uow=mock_uow, user_in=user_create_schema, creator_id=creator_id
    )

    # Assert
    mock_uow.users.get_by_email.assert_awaited_once_with(user_create_schema.email)
    mock_get_password_hash.assert_called_once_with(user_create_schema.password)
    mock_uow.users.create.assert_awaited_once()
    created_user_arg = mock_uow.users.create.call_args.kwargs["obj_in"]
    assert created_user_arg.email == user_create_schema.email
    assert created_user_arg.hashed_password == "hashed_password_string"
    assert created_user_arg.created_by == creator_id
    assert created_user_arg.updated_by == creator_id
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
    creator_id = uuid.uuid4()
    # Act & Assert
    with pytest.raises(UserAlreadyExistsError):
        await user_service.create_user(
            uow=mock_uow, user_in=user_create_schema, creator_id=creator_id
        )

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


@pytest.mark.asyncio
@patch("backend.services.user.get_password_hash", return_value="hashed_password_string")
async def test_ensure_initial_superuser_creates_new(
    mock_get_password_hash: MagicMock,
    user_service: UserService,
    mock_uow: AsyncMock,
    db_superuser: User,
):
    """Ensure superuser is created when missing."""
    mock_uow.users.get_by_email.return_value = None
    mock_uow.users.create.return_value = db_superuser

    result = await user_service.ensure_initial_superuser(
        uow=mock_uow,
        email="admin@example.com",
        password="super-secret",
        full_name="Admin User",
    )

    mock_uow.users.get_by_email.assert_awaited_once_with(email="admin@example.com")
    mock_get_password_hash.assert_called_once_with("super-secret")
    create_obj = mock_uow.users.create.call_args.kwargs["obj_in"]
    assert create_obj.is_superuser is True
    assert create_obj.is_active is True
    assert create_obj.full_name == "Admin User"
    assert isinstance(result, UserRead)
    assert result.email == "admin@example.com"
    mock_uow.users.update.assert_not_awaited()


@pytest.mark.asyncio
@patch("backend.services.user.verify_password", return_value=False)
@patch("backend.services.user.get_password_hash", return_value="new_hash")
async def test_ensure_initial_superuser_upgrades_existing(
    mock_get_password_hash: MagicMock,
    mock_verify_password: MagicMock,
    user_service: UserService,
    mock_uow: AsyncMock,
    db_user: User,
):
    """Ensure existing user is upgraded to superuser."""
    mock_uow.users.get_by_email.return_value = db_user
    mock_uow.users.update.return_value = db_user

    result = await user_service.ensure_initial_superuser(
        uow=mock_uow,
        email=db_user.email,
        password="new-secret",
        full_name="Updated Name",
    )

    mock_uow.users.get_by_email.assert_awaited_once_with(email=db_user.email)
    mock_verify_password.assert_called_once_with("new-secret", "hashed_password_string")
    mock_get_password_hash.assert_called_once_with("new-secret")
    mock_uow.users.update.assert_awaited_once()
    assert db_user.is_superuser is True
    assert db_user.full_name == "Updated Name"
    assert isinstance(result, UserRead)
    assert result.email == db_user.email
