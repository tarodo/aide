import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.models import User
from backend.repositories.user import UserRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """Fixture for a mocked AsyncSession."""
    session = AsyncMock()
    # session.add() is synchronous, not async
    session.add = MagicMock()
    return session


@pytest.fixture
def user_repository(mock_session: AsyncMock) -> UserRepository:
    """Fixture for a UserRepository with a mocked session."""
    return UserRepository(session=mock_session)


@pytest.fixture
def test_user() -> User:
    """Fixture for a sample User object."""
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        full_name="Test User",
        hashed_password="hashed_password",
    )


@pytest.mark.asyncio
async def test_get_by_email(
    user_repository: UserRepository, mock_session: AsyncMock, test_user: User
):
    """Test getting a user by email."""
    # Arrange
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = test_user
    mock_session.execute.return_value = mock_result

    # Act
    result = await user_repository.get_by_email(test_user.email)

    # Assert
    assert result == test_user
    # Verify the query construction
    call_args = mock_session.execute.call_args[0]
    executed_stmt = call_args[0]
    expected_stmt = select(User).where(User.email == test_user.email)

    # Note: Direct comparison of SQLAlchemy statements can be tricky.
    # Comparing their string representation is a common and pragmatic approach for tests.
    assert str(executed_stmt) == str(expected_stmt)


@pytest.mark.asyncio
async def test_get_by_email_not_found(
    user_repository: UserRepository, mock_session: AsyncMock
):
    """Test getting a non-existent user by email."""
    # Arrange
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    # Act
    result = await user_repository.get_by_email("nonexistent@example.com")

    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_get(
    user_repository: UserRepository, mock_session: AsyncMock, test_user: User
):
    """Test the generic get method."""
    # Arrange
    mock_session.get.return_value = test_user

    # Act
    result = await user_repository.get(test_user.id)

    # Assert
    assert result == test_user
    mock_session.get.assert_awaited_once_with(User, test_user.id)


@pytest.mark.asyncio
async def test_get_multi(
    user_repository: UserRepository, mock_session: AsyncMock, test_user: User
):
    """Test the generic get_multi method."""
    # Arrange
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [test_user]
    mock_session.execute.return_value = mock_result

    # Act
    result = await user_repository.get_multi(skip=0, limit=10)

    # Assert
    assert result == [test_user]
    call_args = mock_session.execute.call_args[0]
    executed_stmt = call_args[0]
    expected_stmt = select(User).offset(0).limit(10)
    assert str(executed_stmt) == str(expected_stmt)


@pytest.mark.asyncio
async def test_create(
    user_repository: UserRepository, mock_session: AsyncMock, test_user: User
):
    """Test the generic create method."""
    # Act
    result = await user_repository.create(obj_in=test_user)

    # Assert
    assert result == test_user
    mock_session.add.assert_called_once_with(test_user)
    mock_session.flush.assert_awaited_once()
    mock_session.refresh.assert_awaited_once_with(test_user)


@pytest.mark.asyncio
async def test_update(
    user_repository: UserRepository, mock_session: AsyncMock, test_user: User
):
    """Test the generic update method."""
    # Act
    result = await user_repository.update(db_obj=test_user)

    # Assert
    assert result == test_user
    mock_session.add.assert_called_once_with(test_user)
    mock_session.flush.assert_awaited_once()
    mock_session.refresh.assert_awaited_once_with(test_user)


@pytest.mark.asyncio
async def test_delete(
    user_repository: UserRepository, mock_session: AsyncMock, test_user: User
):
    """Test the generic delete method."""
    # Act
    result = await user_repository.delete(db_obj=test_user)

    # Assert
    assert result == test_user
    mock_session.delete.assert_called_once_with(test_user)
    mock_session.flush.assert_awaited_once()
