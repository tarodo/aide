import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.models.data_type import DataType
from backend.repositories.data_type import DataTypeRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """Fixture for a mocked AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def data_type_repository(mock_session: AsyncMock) -> DataTypeRepository:
    """Fixture for a DataTypeRepository with a mocked session."""
    return DataTypeRepository(session=mock_session)


@pytest.fixture
def test_data_type() -> DataType:
    """Fixture for a sample DataType object."""
    return DataType(
        id=uuid.uuid4(),
        code="VARCHAR",
        system_flavor_id=uuid.uuid4(),
        params_schema={"length": 255},
    )


@pytest.mark.asyncio
async def test_get_by_system_flavor_and_code(
    data_type_repository: DataTypeRepository,
    mock_session: AsyncMock,
    test_data_type: DataType,
):
    """Test getting a data type by system flavor and code."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = test_data_type
    mock_session.execute.return_value = mock_result

    result = await data_type_repository.get_by_system_flavor_and_code(
        test_data_type.system_flavor_id, test_data_type.code
    )

    assert result == test_data_type
    call_args = mock_session.execute.call_args[0]
    executed_stmt = call_args[0]
    expected_stmt = select(DataType).where(
        DataType.system_flavor_id == test_data_type.system_flavor_id,
        DataType.code == test_data_type.code,
    )
    assert str(executed_stmt) == str(expected_stmt)


@pytest.mark.asyncio
async def test_get_by_system_flavor_and_code_not_found(
    data_type_repository: DataTypeRepository, mock_session: AsyncMock
):
    """Test getting a non-existent data type by system flavor and code."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    result = await data_type_repository.get_by_system_flavor_and_code(
        uuid.uuid4(), "NON_EXISTENT"
    )

    assert result is None
