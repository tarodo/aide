import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import System, SystemFlavor, SystemKind
from backend.models.dataset import DatasetRdbms
from backend.repositories.dataset import DatasetRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """Fixture for a mocked AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def dataset_repository(mock_session: AsyncMock) -> DatasetRepository:
    """Fixture for a DatasetRepository with a mocked session."""
    return DatasetRepository(session=mock_session)


@pytest.fixture
def test_dataset_rdbms() -> DatasetRdbms:
    """Fixture for a sample DatasetRdbms object."""
    now = datetime.now(UTC)
    return DatasetRdbms(
        id=uuid.uuid4(),
        system_id=uuid.uuid4(),
        object_name="test_table",
        kind="rdbms",
        schema_name="public",
        table_name="test_table",
        created_at=now,
        updated_at=now,
        is_active=True,
    )


@pytest.mark.asyncio
class TestDatasetRepository:
    async def test_get(
        self,
        dataset_repository: DatasetRepository,
        mock_session: AsyncMock,
        test_dataset_rdbms: DatasetRdbms,
    ):
        """Test getting a dataset by ID with polymorphic loading."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = test_dataset_rdbms
        mock_session.execute.return_value = mock_result

        result = await dataset_repository.get(test_dataset_rdbms.id)

        assert result == test_dataset_rdbms
        mock_session.execute.assert_awaited_once()
        call_args = mock_session.execute.call_args[0]
        executed_stmt = str(call_args[0])
        # Check for polymorphic loading via LEFT OUTER JOIN on child tables
        assert "LEFT OUTER JOIN" in executed_stmt
        assert "dataset_rdbms" in executed_stmt

    async def test_get_multi_paginated(
        self,
        dataset_repository: DatasetRepository,
        mock_session: AsyncMock,
        test_dataset_rdbms: DatasetRdbms,
    ):
        """Test getting multiple datasets with polymorphic loading."""
        mock_total_result = MagicMock()
        mock_total_result.scalar_one.return_value = 1
        mock_items_result = MagicMock()
        mock_items_result.scalars.return_value.all.return_value = [test_dataset_rdbms]
        mock_session.execute.side_effect = [mock_total_result, mock_items_result]

        items, total = await dataset_repository.get_multi_paginated(skip=0, limit=10)

        assert total == 1
        assert items == [test_dataset_rdbms]
        assert mock_session.execute.call_count == 2

    async def test_get_by_system_and_object_name(
        self,
        dataset_repository: DatasetRepository,
        mock_session: AsyncMock,
        test_dataset_rdbms: DatasetRdbms,
    ):
        """Test getting a dataset by system and object name with polymorphic loading."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = test_dataset_rdbms
        mock_session.execute.return_value = mock_result

        result = await dataset_repository.get_by_system_and_object_name(
            test_dataset_rdbms.system_id, test_dataset_rdbms.object_name
        )

        assert result == test_dataset_rdbms
        mock_session.execute.assert_awaited_once()
        call_args = mock_session.execute.call_args[0]
        executed_stmt = str(call_args[0])
        # Check for polymorphic loading via LEFT OUTER JOIN on child tables
        assert "LEFT OUTER JOIN" in executed_stmt
        assert "dataset_rdbms" in executed_stmt


async def _make_system(session: AsyncSession, *, code_suffix: str) -> System:
    kind = SystemKind(code=f"KIND_DST_{code_suffix}", name=f"Kind DST {code_suffix}")
    flavor = SystemFlavor(
        code=f"FL_DST_{code_suffix}", name=f"Flavor DST {code_suffix}", kind=kind
    )
    system = System(
        code=f"SYS_DST_{code_suffix}", name=f"System DST {code_suffix}", flavor=flavor
    )
    session.add_all([kind, flavor, system])
    await session.flush()
    return system


@pytest.mark.asyncio
async def test_dataset_pattern_code_roundtrip(transactional_session: AsyncSession):
    seeded_system = await _make_system(transactional_session, code_suffix="PC_RT")
    ds = DatasetRdbms(
        system_id=seeded_system.id,
        object_name="pc_rt",
        kind="rdbms",
        schema_name="s",
        table_name="pc_rt",
        pattern_code="scd2",
    )
    transactional_session.add(ds)
    await transactional_session.flush()
    await transactional_session.refresh(ds)
    assert ds.pattern_code == "scd2"
