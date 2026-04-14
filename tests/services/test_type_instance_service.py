import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.data_type import DataType
from backend.models.type_instance import TypeInstance
from backend.schemas.type_instance import TypeInstanceCreate, TypeInstanceUpdate
from backend.services.type_instance import TypeInstanceService


class _MockRepository:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()
        self.create: AsyncMock = AsyncMock()
        self.update: AsyncMock = AsyncMock()
        self.delete: AsyncMock = AsyncMock()
        self.get_multi_paginated: AsyncMock = AsyncMock()
        self.get_by_parent_and_slot: AsyncMock = AsyncMock()


class _MockDataTypes:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockTypeInstances:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()
        self.get_by_parent_and_slot: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.data_types = _MockDataTypes()
        self.type_instances = _MockTypeInstances()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


def _make_data_type(params_schema: dict | None = None) -> DataType:
    return DataType(
        id=uuid.uuid4(),
        code="NUMERIC",
        params_schema=params_schema,
        row_version=1,
    )


def _make_type_instance(
    data_type: DataType, type_params: dict | None = None
) -> TypeInstance:
    now = datetime.now(UTC)
    return TypeInstance(
        id=uuid.uuid4(),
        data_type_id=data_type.id,
        type_params=type_params,
        parent_id=None,
        slot=None,
        created_at=now,
        updated_at=now,
        row_version=1,
    )


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    return _MockUnitOfWork()


@pytest.fixture
def type_instance_service() -> TypeInstanceService:
    return TypeInstanceService()


@pytest.mark.asyncio
class TestTypeInstanceServiceParamsValidation:
    async def test_create_rejects_missing_required_param(
        self,
        type_instance_service: TypeInstanceService,
        mock_uow: _MockUnitOfWork,
    ):
        """create() must raise PARAMS_INVALID when a required param is absent."""
        data_type = _make_data_type(
            params_schema={"length": {"type": "int", "required": True, "min": 1}}
        )
        mock_uow.data_types.get.return_value = data_type

        create_schema = TypeInstanceCreate(
            data_type_id=data_type.id,
            type_params={},  # missing required "length"
        )
        mock_repo = _MockRepository()

        with patch.object(
            type_instance_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await type_instance_service.create(
                    uow=mock_uow,
                    obj_in=create_schema,
                )
        assert exc_info.value.error_code == errors.TYPE_INSTANCE_PARAMS_INVALID

    async def test_create_accepts_valid_params(
        self,
        type_instance_service: TypeInstanceService,
        mock_uow: _MockUnitOfWork,
    ):
        """create() must succeed and round-trip type_params when params are valid."""
        params_schema = {
            "precision": {"type": "int", "required": False, "min": 1, "max": 1000},
            "scale": {"type": "int", "required": False, "min": -1000, "max": 1000},
        }
        data_type = _make_data_type(params_schema=params_schema)
        valid_params = {"precision": 10, "scale": 2}

        create_schema = TypeInstanceCreate(
            data_type_id=data_type.id,
            type_params=valid_params,
        )
        db_instance = _make_type_instance(data_type, type_params=valid_params)

        mock_uow.data_types.get.return_value = data_type
        mock_repo = _MockRepository()
        mock_repo.create.return_value = db_instance

        with patch.object(
            type_instance_service, "_get_repository", return_value=mock_repo
        ):
            result = await type_instance_service.create(
                uow=mock_uow,
                obj_in=create_schema,
            )

        mock_repo.create.assert_awaited_once()
        assert result.type_params == valid_params

    async def test_update_rejects_invalid_params(
        self,
        type_instance_service: TypeInstanceService,
        mock_uow: _MockUnitOfWork,
    ):
        """update() must raise PARAMS_INVALID when updated type_params violate schema."""
        params_schema = {
            "precision": {"type": "int", "required": False, "min": 1, "max": 1000},
        }
        data_type = _make_data_type(params_schema=params_schema)
        db_instance = _make_type_instance(data_type, type_params={"precision": 10})

        update_schema = TypeInstanceUpdate(
            type_params={"precision": 1001},  # exceeds max of 1000
            row_version=1,
        )

        mock_uow.data_types.get.return_value = data_type
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_instance

        with patch.object(
            type_instance_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await type_instance_service.update(
                    uow=mock_uow,
                    obj_id=db_instance.id,
                    obj_in=update_schema,
                )
        assert exc_info.value.error_code == errors.TYPE_INSTANCE_PARAMS_INVALID
