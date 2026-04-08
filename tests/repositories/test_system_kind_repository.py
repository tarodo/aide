import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.models.system_kind import SystemKind
from backend.repositories.system_kind import SystemKindRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """Fixture for a mocked AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def system_kind_repository(mock_session: AsyncMock) -> SystemKindRepository:
    """Fixture for a SystemKindRepository with a mocked session."""
    return SystemKindRepository(session=mock_session)


@pytest.fixture
def test_system_kind() -> SystemKind:
    """Fixture for a sample SystemKind object."""
    return SystemKind(
        id=uuid.uuid4(),
        code="RDBMS",
        name="Relational Database",
    )


@pytest.mark.asyncio
async def test_get_by_code(
    system_kind_repository: SystemKindRepository,
    mock_session: AsyncMock,
    test_system_kind: SystemKind,
):
    """Test getting a system kind by code."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = test_system_kind
    mock_session.execute.return_value = mock_result

    result = await system_kind_repository.get_by_code(test_system_kind.code)

    assert result == test_system_kind
    call_args = mock_session.execute.call_args[0]
    executed_stmt = call_args[0]
    expected_stmt = select(SystemKind).where(
        SystemKind.code == test_system_kind.code,
        SystemKind.deleted_at.is_(None),
    )
    assert str(executed_stmt) == str(expected_stmt)


@pytest.mark.asyncio
async def test_get_by_code_not_found(
    system_kind_repository: SystemKindRepository, mock_session: AsyncMock
):
    """Test getting a non-existent system kind by code."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    result = await system_kind_repository.get_by_code("NON_EXISTENT")

    assert result is None
