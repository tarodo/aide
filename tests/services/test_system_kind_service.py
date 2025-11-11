import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.system_kind import SystemKind
from backend.schemas.pagination import Page
from backend.schemas.system_kind import (
    SystemKindCreate,
    SystemKindRead,
    SystemKindUpdate,
)
from backend.services.system_kind import SystemKindService


class _MockSystemKinds:
    def __init__(self) -> None:
        self.get_by_code: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()
        self.create: AsyncMock = AsyncMock()
        self.update: AsyncMock = AsyncMock()
        self.delete: AsyncMock = AsyncMock()
        self.get_multi_paginated: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.system_kinds = _MockSystemKinds()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    """Fixture for a mocked UnitOfWork."""
    return _MockUnitOfWork()


@pytest.fixture
def system_kind_service() -> SystemKindService:
    """Fixture for a SystemKindService instance."""
    return SystemKindService()


@pytest.fixture
def system_kind_create_schema() -> SystemKindCreate:
    """Fixture for a SystemKindCreate schema object."""
    return SystemKindCreate(code="RDBMS", name="Relational Database")


@pytest.fixture
def db_system_kind() -> SystemKind:
    """Fixture for a database SystemKind model object."""
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    return SystemKind(
        id=uuid.uuid4(),
        code="RDBMS",
        name="Relational Database",
        created_by=user_id,
        updated_by=user_id,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
class TestSystemKindService:
    async def test_create_system_kind_success(
        self,
        system_kind_service: SystemKindService,
        mock_uow: _MockUnitOfWork,
        system_kind_create_schema: SystemKindCreate,
        db_system_kind: SystemKind,
    ):
        mock_uow.system_kinds.get_by_code.return_value = None
        mock_uow.system_kinds.create.return_value = db_system_kind
        creator_id = uuid.uuid4()

        result = await system_kind_service.create_system_kind(
            uow=mock_uow,
            system_kind_in=system_kind_create_schema,
            creator_id=creator_id,
        )

        mock_uow.system_kinds.get_by_code.assert_awaited_once_with(
            system_kind_create_schema.code
        )
        mock_uow.system_kinds.create.assert_awaited_once()
        created_arg = mock_uow.system_kinds.create.call_args.kwargs["obj_in"]
        assert created_arg.code == system_kind_create_schema.code
        assert created_arg.created_by == creator_id
        assert isinstance(result, SystemKindRead)
        assert result.code == db_system_kind.code

    async def test_create_system_kind_duplicate_code(
        self,
        system_kind_service: SystemKindService,
        mock_uow: _MockUnitOfWork,
        system_kind_create_schema: SystemKindCreate,
        db_system_kind: SystemKind,
    ):
        mock_uow.system_kinds.get_by_code.return_value = db_system_kind

        with pytest.raises(AppException) as exc_info:
            await system_kind_service.create_system_kind(
                uow=mock_uow,
                system_kind_in=system_kind_create_schema,
                creator_id=uuid.uuid4(),
            )
        assert exc_info.value.error_code == errors.SYSTEM_KIND_ALREADY_EXISTS

    async def test_get_system_kind_success(
        self,
        system_kind_service: SystemKindService,
        mock_uow: _MockUnitOfWork,
        db_system_kind: SystemKind,
    ):
        mock_uow.system_kinds.get.return_value = db_system_kind
        result = await system_kind_service.get_system_kind(
            uow=mock_uow, system_kind_id=db_system_kind.id
        )
        assert isinstance(result, SystemKindRead)
        assert result.id == db_system_kind.id

    async def test_get_system_kind_not_found(
        self, system_kind_service: SystemKindService, mock_uow: _MockUnitOfWork
    ):
        mock_uow.system_kinds.get.return_value = None
        with pytest.raises(AppException) as exc_info:
            await system_kind_service.get_system_kind(
                uow=mock_uow, system_kind_id=uuid.uuid4()
            )
        assert exc_info.value.error_code == errors.SYSTEM_KIND_NOT_FOUND

    async def test_get_system_kinds_paginated(
        self,
        system_kind_service: SystemKindService,
        mock_uow: _MockUnitOfWork,
        db_system_kind: SystemKind,
    ):
        mock_uow.system_kinds.get_multi_paginated.return_value = ([db_system_kind], 1)
        result = await system_kind_service.get_system_kinds_paginated(
            uow=mock_uow, page=1, size=10
        )
        assert isinstance(result, Page)
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].id == db_system_kind.id

    async def test_update_system_kind_success(
        self,
        system_kind_service: SystemKindService,
        mock_uow: _MockUnitOfWork,
        db_system_kind: SystemKind,
    ):
        update_schema = SystemKindUpdate(name="New Name")
        mock_uow.system_kinds.get.return_value = db_system_kind
        mock_uow.system_kinds.update.return_value = db_system_kind
        updater_id = uuid.uuid4()

        result = await system_kind_service.update_system_kind(
            uow=mock_uow,
            system_kind_id=db_system_kind.id,
            system_kind_in=update_schema,
            updater_id=updater_id,
        )

        mock_uow.system_kinds.update.assert_awaited_once()
        updated_arg = mock_uow.system_kinds.update.call_args.kwargs["db_obj"]
        assert updated_arg.name == "New Name"
        assert updated_arg.updated_by == updater_id
        assert result.name == "New Name"

    async def test_delete_system_kind_success(
        self,
        system_kind_service: SystemKindService,
        mock_uow: _MockUnitOfWork,
        db_system_kind: SystemKind,
    ):
        mock_uow.system_kinds.get.return_value = db_system_kind
        mock_uow.system_kinds.delete.return_value = db_system_kind

        result = await system_kind_service.delete_system_kind(
            uow=mock_uow, system_kind_id=db_system_kind.id
        )

        mock_uow.system_kinds.delete.assert_awaited_once_with(db_obj=db_system_kind)
        assert result.id == db_system_kind.id
