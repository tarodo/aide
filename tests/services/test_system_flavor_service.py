import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.system_flavor import SystemFlavor
from backend.models.system_kind import SystemKind
from backend.schemas.pagination import Page
from backend.schemas.system_flavor import (
    SystemFlavorCreate,
    SystemFlavorRead,
    SystemFlavorUpdate,
)
from backend.services.system_flavor import SystemFlavorService


class _MockSystemFlavors:
    def __init__(self) -> None:
        self.get_by_code: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()
        self.create: AsyncMock = AsyncMock()
        self.update: AsyncMock = AsyncMock()
        self.delete: AsyncMock = AsyncMock()
        self.get_multi_paginated: AsyncMock = AsyncMock()


class _MockSystemKinds:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.system_flavors = _MockSystemFlavors()
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
def system_flavor_service() -> SystemFlavorService:
    """Fixture for a SystemFlavorService instance."""
    return SystemFlavorService()


@pytest.fixture
def db_system_kind() -> SystemKind:
    """Fixture for a database SystemKind model object."""
    return SystemKind(id=uuid.uuid4(), code="RDBMS", name="Relational Database")


@pytest.fixture
def system_flavor_create_schema(db_system_kind: SystemKind) -> SystemFlavorCreate:
    """Fixture for a SystemFlavorCreate schema object."""
    return SystemFlavorCreate(
        code="POSTGRESQL",
        name="PostgreSQL",
        vendor="The PostgreSQL Global Development Group",
        version="16",
        kind_id=db_system_kind.id,
    )


@pytest.fixture
def db_system_flavor(db_system_kind: SystemKind) -> SystemFlavor:
    """Fixture for a database SystemFlavor model object."""
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    return SystemFlavor(
        id=uuid.uuid4(),
        code="POSTGRESQL",
        name="PostgreSQL",
        vendor="The PostgreSQL Global Development Group",
        version="16",
        kind_id=db_system_kind.id,
        created_by=user_id,
        updated_by=user_id,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
class TestSystemFlavorService:
    async def test_create_system_flavor_success(
        self,
        system_flavor_service: SystemFlavorService,
        mock_uow: _MockUnitOfWork,
        system_flavor_create_schema: SystemFlavorCreate,
        db_system_flavor: SystemFlavor,
        db_system_kind: SystemKind,
    ):
        mock_uow.system_flavors.get_by_code.return_value = None
        mock_uow.system_kinds.get.return_value = db_system_kind
        mock_uow.system_flavors.create.return_value = db_system_flavor
        creator_id = uuid.uuid4()

        result = await system_flavor_service.create_system_flavor(
            uow=mock_uow,
            system_flavor_in=system_flavor_create_schema,
            creator_id=creator_id,
        )

        mock_uow.system_flavors.get_by_code.assert_awaited_once_with(
            system_flavor_create_schema.code
        )
        mock_uow.system_kinds.get.assert_awaited_once_with(
            system_flavor_create_schema.kind_id
        )
        mock_uow.system_flavors.create.assert_awaited_once()
        created_arg = mock_uow.system_flavors.create.call_args.kwargs["obj_in"]
        assert created_arg.code == system_flavor_create_schema.code
        assert created_arg.created_by == creator_id
        assert isinstance(result, SystemFlavorRead)
        assert result.code == db_system_flavor.code

    async def test_create_system_flavor_duplicate_code(
        self,
        system_flavor_service: SystemFlavorService,
        mock_uow: _MockUnitOfWork,
        system_flavor_create_schema: SystemFlavorCreate,
        db_system_flavor: SystemFlavor,
    ):
        mock_uow.system_flavors.get_by_code.return_value = db_system_flavor

        with pytest.raises(AppException) as exc_info:
            await system_flavor_service.create_system_flavor(
                uow=mock_uow,
                system_flavor_in=system_flavor_create_schema,
                creator_id=uuid.uuid4(),
            )
        assert exc_info.value.error_code == errors.SYSTEM_FLAVOR_ALREADY_EXISTS

    async def test_create_system_flavor_kind_not_found(
        self,
        system_flavor_service: SystemFlavorService,
        mock_uow: _MockUnitOfWork,
        system_flavor_create_schema: SystemFlavorCreate,
    ):
        mock_uow.system_flavors.get_by_code.return_value = None
        mock_uow.system_kinds.get.return_value = None

        with pytest.raises(AppException) as exc_info:
            await system_flavor_service.create_system_flavor(
                uow=mock_uow,
                system_flavor_in=system_flavor_create_schema,
                creator_id=uuid.uuid4(),
            )
        assert exc_info.value.error_code == errors.SYSTEM_KIND_NOT_FOUND

    async def test_get_system_flavor_success(
        self,
        system_flavor_service: SystemFlavorService,
        mock_uow: _MockUnitOfWork,
        db_system_flavor: SystemFlavor,
    ):
        mock_uow.system_flavors.get.return_value = db_system_flavor
        result = await system_flavor_service.get_system_flavor(
            uow=mock_uow, system_flavor_id=db_system_flavor.id
        )
        assert isinstance(result, SystemFlavorRead)
        assert result.id == db_system_flavor.id

    async def test_get_system_flavor_not_found(
        self, system_flavor_service: SystemFlavorService, mock_uow: _MockUnitOfWork
    ):
        mock_uow.system_flavors.get.return_value = None
        with pytest.raises(AppException) as exc_info:
            await system_flavor_service.get_system_flavor(
                uow=mock_uow, system_flavor_id=uuid.uuid4()
            )
        assert exc_info.value.error_code == errors.SYSTEM_FLAVOR_NOT_FOUND

    async def test_get_system_flavors_paginated(
        self,
        system_flavor_service: SystemFlavorService,
        mock_uow: _MockUnitOfWork,
        db_system_flavor: SystemFlavor,
    ):
        mock_uow.system_flavors.get_multi_paginated.return_value = (
            [db_system_flavor],
            1,
        )
        result = await system_flavor_service.get_system_flavors_paginated(
            uow=mock_uow, page=1, size=10
        )
        assert isinstance(result, Page)
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].id == db_system_flavor.id

    async def test_update_system_flavor_success(
        self,
        system_flavor_service: SystemFlavorService,
        mock_uow: _MockUnitOfWork,
        db_system_flavor: SystemFlavor,
    ):
        update_schema = SystemFlavorUpdate(name="New Name")
        mock_uow.system_flavors.get.return_value = db_system_flavor
        mock_uow.system_flavors.update.return_value = db_system_flavor
        updater_id = uuid.uuid4()

        result = await system_flavor_service.update_system_flavor(
            uow=mock_uow,
            system_flavor_id=db_system_flavor.id,
            system_flavor_in=update_schema,
            updater_id=updater_id,
        )

        mock_uow.system_flavors.update.assert_awaited_once()
        updated_arg = mock_uow.system_flavors.update.call_args.kwargs["db_obj"]
        assert updated_arg.name == "New Name"
        assert updated_arg.updated_by == updater_id
        assert result.name == "New Name"

    async def test_delete_system_flavor_success(
        self,
        system_flavor_service: SystemFlavorService,
        mock_uow: _MockUnitOfWork,
        db_system_flavor: SystemFlavor,
    ):
        mock_uow.system_flavors.get.return_value = db_system_flavor
        mock_uow.system_flavors.delete.return_value = db_system_flavor

        result = await system_flavor_service.delete_system_flavor(
            uow=mock_uow, system_flavor_id=db_system_flavor.id
        )

        mock_uow.system_flavors.delete.assert_awaited_once_with(db_obj=db_system_flavor)
        assert result.id == db_system_flavor.id
