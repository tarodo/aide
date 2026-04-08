import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.models.system_flavor import SystemFlavor
from backend.repositories.system_flavor import SystemFlavorRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """Fixture for a mocked AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def system_flavor_repository(mock_session: AsyncMock) -> SystemFlavorRepository:
    """Fixture for a SystemFlavorRepository with a mocked session."""
    return SystemFlavorRepository(session=mock_session)


@pytest.fixture
def test_system_flavor() -> SystemFlavor:
    """Fixture for a sample SystemFlavor object."""
    return SystemFlavor(
        id=uuid.uuid4(),
        code="POSTGRESQL",
        name="PostgreSQL",
        kind_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_get_by_code(
    system_flavor_repository: SystemFlavorRepository,
    mock_session: AsyncMock,
    test_system_flavor: SystemFlavor,
):
    """Test getting a system flavor by code."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = test_system_flavor
    mock_session.execute.return_value = mock_result

    result = await system_flavor_repository.get_by_code(test_system_flavor.code)

    assert result == test_system_flavor
    call_args = mock_session.execute.call_args[0]
    executed_stmt = call_args[0]
    expected_stmt = select(SystemFlavor).where(
        SystemFlavor.code == test_system_flavor.code,
        SystemFlavor.deleted_at.is_(None),
    )
    assert str(executed_stmt) == str(expected_stmt)


@pytest.mark.asyncio
async def test_get_by_code_not_found(
    system_flavor_repository: SystemFlavorRepository, mock_session: AsyncMock
):
    """Test getting a non-existent system flavor by code."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    result = await system_flavor_repository.get_by_code("NON_EXISTENT")

    assert result is None
