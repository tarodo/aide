import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.models.field import Field
from backend.repositories.field import FieldRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """Fixture for a mocked AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def field_repository(mock_session: AsyncMock) -> FieldRepository:
    """Fixture for a FieldRepository with a mocked session."""
    return FieldRepository(session=mock_session)


@pytest.fixture
def test_field() -> Field:
    """Fixture for a sample Field object."""
    return Field(
        id=uuid.uuid4(),
        name="email",
        dataset_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_get_by_dataset_and_name(
    field_repository: FieldRepository,
    mock_session: AsyncMock,
    test_field: Field,
):
    """Test getting a field by dataset and name."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = test_field
    mock_session.execute.return_value = mock_result

    result = await field_repository.get_by_dataset_and_name(
        test_field.dataset_id, test_field.name
    )

    assert result == test_field
    call_args = mock_session.execute.call_args[0]
    executed_stmt = call_args[0]
    expected_stmt = select(Field).where(
        Field.dataset_id == test_field.dataset_id,
        Field.name == test_field.name,
    )
    assert str(executed_stmt) == str(expected_stmt)


@pytest.mark.asyncio
async def test_get_by_dataset_and_name_not_found(
    field_repository: FieldRepository, mock_session: AsyncMock
):
    """Test getting a non-existent field by dataset and name."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    result = await field_repository.get_by_dataset_and_name(
        uuid.uuid4(), "non_existent"
    )

    assert result is None
