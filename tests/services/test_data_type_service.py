import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.data_type import DataType
from backend.models.system_flavor import SystemFlavor
from backend.schemas.data_type import (
    DataTypeCreate,
    DataTypeRead,
    DataTypeUpdate,
)
from backend.schemas.pagination import Page
from backend.services.data_type import DataTypeService


class _MockRepository:
    def __init__(self) -> None:
        self.get_by_system_flavor_and_code: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()
        self.create: AsyncMock = AsyncMock()
        self.update: AsyncMock = AsyncMock()
        self.delete: AsyncMock = AsyncMock()
        self.restore: AsyncMock = AsyncMock()
        self.get_including_deleted: AsyncMock = AsyncMock()
        self.get_multi_paginated: AsyncMock = AsyncMock()


class _MockSystemFlavors:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.system_flavors = _MockSystemFlavors()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    """Fixture for a mocked UnitOfWork."""
    return _MockUnitOfWork()


@pytest.fixture
def data_type_service() -> DataTypeService:
    """Fixture for a DataTypeService instance."""
    return DataTypeService()


@pytest.fixture
def db_system_flavor() -> SystemFlavor:
    """Fixture for a database SystemFlavor model object."""
    return SystemFlavor(
        id=uuid.uuid4(), code="POSTGRESQL", name="PostgreSQL", kind_id=uuid.uuid4()
    )


@pytest.fixture
def data_type_create_schema(db_system_flavor: SystemFlavor) -> DataTypeCreate:
    """Fixture for a DataTypeCreate schema object."""
    return DataTypeCreate(
        system_flavor_id=db_system_flavor.id,
        code="VARCHAR",
        params_schema={"length": {"type": "integer"}},
        render_template="VARCHAR({{ length }})",
    )


@pytest.fixture
def db_data_type(db_system_flavor: SystemFlavor) -> DataType:
    """Fixture for a database DataType model object."""
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    return DataType(
        id=uuid.uuid4(),
        system_flavor_id=db_system_flavor.id,
        code="VARCHAR",
        params_schema={"length": {"type": "integer"}},
        render_template="VARCHAR({{ length }})",
        created_by=user_id,
        updated_by=user_id,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
class TestDataTypeService:
    async def test_create_data_type_success(
        self,
        data_type_service: DataTypeService,
        mock_uow: _MockUnitOfWork,
        data_type_create_schema: DataTypeCreate,
        db_data_type: DataType,
        db_system_flavor: SystemFlavor,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_system_flavor_and_code.return_value = None
        mock_repo.create.return_value = db_data_type
        mock_uow.system_flavors.get.return_value = db_system_flavor
        creator_id = uuid.uuid4()

        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            result = await data_type_service.create(
                uow=mock_uow,
                obj_in=data_type_create_schema,
                creator_id=creator_id,
            )

        mock_repo.get_by_system_flavor_and_code.assert_awaited_once_with(
            data_type_create_schema.system_flavor_id, data_type_create_schema.code
        )
        mock_uow.system_flavors.get.assert_awaited_once_with(
            data_type_create_schema.system_flavor_id
        )
        mock_repo.create.assert_awaited_once()
        created_arg = mock_repo.create.call_args.kwargs["obj_in"]
        assert created_arg.code == data_type_create_schema.code
        assert created_arg.created_by == creator_id
        assert isinstance(result, DataTypeRead)
        assert result.code == db_data_type.code

    async def test_create_data_type_duplicate(
        self,
        data_type_service: DataTypeService,
        mock_uow: _MockUnitOfWork,
        data_type_create_schema: DataTypeCreate,
        db_data_type: DataType,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_system_flavor_and_code.return_value = db_data_type

        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await data_type_service.create(
                    uow=mock_uow,
                    obj_in=data_type_create_schema,
                    creator_id=uuid.uuid4(),
                )
        assert exc_info.value.error_code == errors.DATA_TYPE_ALREADY_EXISTS

    async def test_create_data_type_flavor_not_found(
        self,
        data_type_service: DataTypeService,
        mock_uow: _MockUnitOfWork,
        data_type_create_schema: DataTypeCreate,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_system_flavor_and_code.return_value = None
        mock_uow.system_flavors.get.return_value = None

        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await data_type_service.create(
                    uow=mock_uow,
                    obj_in=data_type_create_schema,
                    creator_id=uuid.uuid4(),
                )
        assert exc_info.value.error_code == errors.SYSTEM_FLAVOR_NOT_FOUND

    async def test_get_data_type_success(
        self,
        data_type_service: DataTypeService,
        mock_uow: _MockUnitOfWork,
        db_data_type: DataType,
    ):
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_data_type
        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            result = await data_type_service.get_by_id(
                uow=mock_uow, obj_id=db_data_type.id
            )
        assert isinstance(result, DataTypeRead)
        assert result.id == db_data_type.id

    async def test_get_data_type_not_found(
        self, data_type_service: DataTypeService, mock_uow: _MockUnitOfWork
    ):
        mock_repo = _MockRepository()
        mock_repo.get.return_value = None
        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await data_type_service.get_by_id(uow=mock_uow, obj_id=uuid.uuid4())
        assert exc_info.value.error_code == errors.DATA_TYPE_NOT_FOUND

    async def test_get_data_types_paginated(
        self,
        data_type_service: DataTypeService,
        mock_uow: _MockUnitOfWork,
        db_data_type: DataType,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_multi_paginated.return_value = ([db_data_type], 1)
        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            result = await data_type_service.get_paginated(
                uow=mock_uow, page=1, size=10
            )
        assert isinstance(result, Page)
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].id == db_data_type.id

    async def test_update_data_type_success(
        self,
        data_type_service: DataTypeService,
        mock_uow: _MockUnitOfWork,
        db_data_type: DataType,
    ):
        update_schema = DataTypeUpdate(code="TEXT")
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_data_type
        mock_repo.get_by_system_flavor_and_code.return_value = None
        mock_repo.update.return_value = db_data_type
        updater_id = uuid.uuid4()

        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            result = await data_type_service.update(
                uow=mock_uow,
                obj_id=db_data_type.id,
                obj_in=update_schema,
                updater_id=updater_id,
            )

        mock_repo.update.assert_awaited_once()
        updated_arg = mock_repo.update.call_args.kwargs["db_obj"]
        assert updated_arg.code == "TEXT"
        assert updated_arg.updated_by == updater_id
        assert result.code == "TEXT"

    async def test_delete_data_type_success(
        self,
        data_type_service: DataTypeService,
        mock_uow: _MockUnitOfWork,
        db_data_type: DataType,
    ):
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_data_type
        mock_repo.delete.return_value = db_data_type

        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            result = await data_type_service.delete(
                uow=mock_uow, obj_id=db_data_type.id
            )

        mock_repo.delete.assert_awaited_once_with(db_obj=db_data_type)
        assert result.id == db_data_type.id

    async def test_delete_sets_deleter_id(
        self,
        data_type_service: DataTypeService,
        mock_uow: _MockUnitOfWork,
        db_data_type: DataType,
    ):
        deleter_id = uuid.uuid4()
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_data_type
        mock_repo.delete.return_value = db_data_type

        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            await data_type_service.delete(
                uow=mock_uow, obj_id=db_data_type.id, deleter_id=deleter_id
            )

        assert db_data_type.deleted_by == deleter_id

    async def test_restore_success(
        self,
        data_type_service: DataTypeService,
        mock_uow: _MockUnitOfWork,
        db_data_type: DataType,
    ):
        db_data_type.deleted_at = datetime.now(UTC)
        mock_repo = _MockRepository()
        mock_repo.get_including_deleted.return_value = db_data_type
        mock_repo.restore.return_value = db_data_type

        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            result = await data_type_service.restore(
                uow=mock_uow, obj_id=db_data_type.id, restorer_id=uuid.uuid4()
            )

        mock_repo.restore.assert_awaited_once_with(db_obj=db_data_type)
        assert result.id == db_data_type.id

    async def test_restore_not_deleted_raises(
        self,
        data_type_service: DataTypeService,
        mock_uow: _MockUnitOfWork,
        db_data_type: DataType,
    ):
        db_data_type.deleted_at = None
        mock_repo = _MockRepository()
        mock_repo.get_including_deleted.return_value = db_data_type

        with patch.object(data_type_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await data_type_service.restore(uow=mock_uow, obj_id=db_data_type.id)
        assert exc_info.value.error_code == errors.ENTITY_NOT_DELETED
