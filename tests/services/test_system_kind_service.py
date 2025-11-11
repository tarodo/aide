import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

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


class _MockRepository:
    def __init__(self) -> None:
        self.get_by_code: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()
        self.create: AsyncMock = AsyncMock()
        self.update: AsyncMock = AsyncMock()
        self.delete: AsyncMock = AsyncMock()
        self.get_multi_paginated: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()

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
        mock_repo = _MockRepository()
        mock_repo.get_by_code.return_value = None
        mock_repo.create.return_value = db_system_kind
        creator_id = uuid.uuid4()

        with patch.object(
            system_kind_service, "_get_repository", return_value=mock_repo
        ):
            result = await system_kind_service.create(
                uow=mock_uow,
                obj_in=system_kind_create_schema,
                creator_id=creator_id,
            )

        mock_repo.get_by_code.assert_awaited_once_with(system_kind_create_schema.code)
        mock_repo.create.assert_awaited_once()
        created_arg = mock_repo.create.call_args.kwargs["obj_in"]
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
        mock_repo = _MockRepository()
        mock_repo.get_by_code.return_value = db_system_kind

        with patch.object(
            system_kind_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await system_kind_service.create(
                    uow=mock_uow,
                    obj_in=system_kind_create_schema,
                    creator_id=uuid.uuid4(),
                )
        assert exc_info.value.error_code == errors.SYSTEM_KIND_ALREADY_EXISTS

    async def test_get_system_kind_success(
        self,
        system_kind_service: SystemKindService,
        mock_uow: _MockUnitOfWork,
        db_system_kind: SystemKind,
    ):
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_system_kind
        with patch.object(
            system_kind_service, "_get_repository", return_value=mock_repo
        ):
            result = await system_kind_service.get_by_id(
                uow=mock_uow, obj_id=db_system_kind.id
            )
        assert isinstance(result, SystemKindRead)
        assert result.id == db_system_kind.id

    async def test_get_system_kind_not_found(
        self, system_kind_service: SystemKindService, mock_uow: _MockUnitOfWork
    ):
        mock_repo = _MockRepository()
        mock_repo.get.return_value = None
        with patch.object(
            system_kind_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await system_kind_service.get_by_id(uow=mock_uow, obj_id=uuid.uuid4())
        assert exc_info.value.error_code == errors.SYSTEM_KIND_NOT_FOUND

    async def test_get_system_kinds_paginated(
        self,
        system_kind_service: SystemKindService,
        mock_uow: _MockUnitOfWork,
        db_system_kind: SystemKind,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_multi_paginated.return_value = ([db_system_kind], 1)
        with patch.object(
            system_kind_service, "_get_repository", return_value=mock_repo
        ):
            result = await system_kind_service.get_paginated(
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
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_system_kind
        mock_repo.update.return_value = db_system_kind
        updater_id = uuid.uuid4()

        with patch.object(
            system_kind_service, "_get_repository", return_value=mock_repo
        ):
            result = await system_kind_service.update(
                uow=mock_uow,
                obj_id=db_system_kind.id,
                obj_in=update_schema,
                updater_id=updater_id,
            )

        mock_repo.update.assert_awaited_once()
        updated_arg = mock_repo.update.call_args.kwargs["db_obj"]
        assert updated_arg.name == "New Name"
        assert updated_arg.updated_by == updater_id
        assert result.name == "New Name"

    async def test_delete_system_kind_success(
        self,
        system_kind_service: SystemKindService,
        mock_uow: _MockUnitOfWork,
        db_system_kind: SystemKind,
    ):
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_system_kind
        mock_repo.delete.return_value = db_system_kind

        with patch.object(
            system_kind_service, "_get_repository", return_value=mock_repo
        ):
            result = await system_kind_service.delete(
                uow=mock_uow, obj_id=db_system_kind.id
            )

        mock_repo.delete.assert_awaited_once_with(db_obj=db_system_kind)
        assert result.id == db_system_kind.id
