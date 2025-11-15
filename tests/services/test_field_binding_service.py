import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models import DatasetSchema, DataType, Field, FieldBinding
from backend.schemas.field_binding import (
    FieldBindingCreate,
    FieldBindingUpdate,
)
from backend.services.field_binding import FieldBindingService


class _MockRepository:
    def __init__(self) -> None:
        self.get_by_dataset_schema_and_field_id: AsyncMock = AsyncMock()
        self.get_by_dataset_schema_and_position: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()
        self.create: AsyncMock = AsyncMock()
        self.update: AsyncMock = AsyncMock()


class _MockFields:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockDatasetSchemas:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockDataTypes:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.fields = _MockFields()
        self.dataset_schemas = _MockDatasetSchemas()
        self.data_types = _MockDataTypes()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    return _MockUnitOfWork()


@pytest.fixture
def field_binding_service() -> FieldBindingService:
    return FieldBindingService()


@pytest.fixture
def db_field() -> Field:
    return Field(id=uuid.uuid4(), name="id")


@pytest.fixture
def db_dataset_schema() -> DatasetSchema:
    return DatasetSchema(id=uuid.uuid4(), version_num=1)


@pytest.fixture
def db_data_type() -> DataType:
    return DataType(id=uuid.uuid4(), code="INT")


@pytest.fixture
def field_binding_create_schema(
    db_field: Field, db_dataset_schema: DatasetSchema, db_data_type: DataType
) -> FieldBindingCreate:
    return FieldBindingCreate(
        field_id=db_field.id,
        dataset_schema_id=db_dataset_schema.id,
        position=1,
        is_nullable=False,
        data_type_id=db_data_type.id,
    )


@pytest.fixture
def db_field_binding(
    field_binding_create_schema: FieldBindingCreate,
) -> FieldBinding:
    now = datetime.now(UTC)
    return FieldBinding(
        id=uuid.uuid4(),
        field_id=field_binding_create_schema.field_id,
        dataset_schema_id=field_binding_create_schema.dataset_schema_id,
        position=field_binding_create_schema.position,
        is_nullable=field_binding_create_schema.is_nullable,
        data_type_id=field_binding_create_schema.data_type_id,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
class TestFieldBindingService:
    async def test_create_duplicate_field_id(
        self,
        field_binding_service: FieldBindingService,
        mock_uow: _MockUnitOfWork,
        field_binding_create_schema: FieldBindingCreate,
        db_field_binding: FieldBinding,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_dataset_schema_and_field_id.return_value = db_field_binding

        with patch.object(
            field_binding_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await field_binding_service.create(
                    uow=mock_uow, obj_in=field_binding_create_schema
                )
        assert exc_info.value.error_code == errors.FIELD_BINDING_FIELD_ID_ALREADY_EXISTS

    async def test_create_duplicate_position(
        self,
        field_binding_service: FieldBindingService,
        mock_uow: _MockUnitOfWork,
        field_binding_create_schema: FieldBindingCreate,
        db_field_binding: FieldBinding,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_dataset_schema_and_field_id.return_value = None
        mock_repo.get_by_dataset_schema_and_position.return_value = db_field_binding

        with patch.object(
            field_binding_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await field_binding_service.create(
                    uow=mock_uow, obj_in=field_binding_create_schema
                )
        assert exc_info.value.error_code == errors.FIELD_BINDING_POSITION_ALREADY_EXISTS

    @pytest.mark.parametrize(
        "missing_entity, error_code",
        [
            ("field", errors.FIELD_NOT_FOUND),
            ("dataset_schema", errors.DATASET_SCHEMA_NOT_FOUND),
            ("data_type", errors.DATA_TYPE_NOT_FOUND),
        ],
    )
    async def test_create_dependency_not_found(
        self,
        field_binding_service: FieldBindingService,
        mock_uow: _MockUnitOfWork,
        field_binding_create_schema: FieldBindingCreate,
        db_field: Field,
        db_dataset_schema: DatasetSchema,
        db_data_type: DataType,
        missing_entity: str,
        error_code: str,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_dataset_schema_and_field_id.return_value = None
        mock_repo.get_by_dataset_schema_and_position.return_value = None

        mock_uow.fields.get.return_value = (
            None if missing_entity == "field" else db_field
        )
        mock_uow.dataset_schemas.get.return_value = (
            None if missing_entity == "dataset_schema" else db_dataset_schema
        )
        mock_uow.data_types.get.return_value = (
            None if missing_entity == "data_type" else db_data_type
        )

        with patch.object(
            field_binding_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await field_binding_service.create(
                    uow=mock_uow, obj_in=field_binding_create_schema
                )
        assert exc_info.value.error_code == error_code

    async def test_update_duplicate_field_id(
        self,
        field_binding_service: FieldBindingService,
        mock_uow: _MockUnitOfWork,
        db_field_binding: FieldBinding,
    ):
        update_schema = FieldBindingUpdate(field_id=uuid.uuid4())
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_field_binding
        mock_repo.get_by_dataset_schema_and_field_id.return_value = FieldBinding(
            id=uuid.uuid4()
        )

        with patch.object(
            field_binding_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await field_binding_service.update(
                    uow=mock_uow, obj_id=db_field_binding.id, obj_in=update_schema
                )
        assert exc_info.value.error_code == errors.FIELD_BINDING_FIELD_ID_ALREADY_EXISTS

    async def test_update_duplicate_position(
        self,
        field_binding_service: FieldBindingService,
        mock_uow: _MockUnitOfWork,
        db_field_binding: FieldBinding,
    ):
        update_schema = FieldBindingUpdate(position=99)
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_field_binding
        mock_repo.get_by_dataset_schema_and_field_id.return_value = None
        mock_repo.get_by_dataset_schema_and_position.return_value = FieldBinding(
            id=uuid.uuid4()
        )

        with patch.object(
            field_binding_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await field_binding_service.update(
                    uow=mock_uow, obj_id=db_field_binding.id, obj_in=update_schema
                )
        assert exc_info.value.error_code == errors.FIELD_BINDING_POSITION_ALREADY_EXISTS

    async def test_update_dependency_not_found(
        self,
        field_binding_service: FieldBindingService,
        mock_uow: _MockUnitOfWork,
        db_field_binding: FieldBinding,
    ):
        update_schema = FieldBindingUpdate(data_type_id=uuid.uuid4())
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_field_binding
        mock_repo.get_by_dataset_schema_and_field_id.return_value = None
        mock_repo.get_by_dataset_schema_and_position.return_value = None
        mock_uow.fields.get.return_value = Field(id=db_field_binding.field_id)
        mock_uow.dataset_schemas.get.return_value = DatasetSchema(
            id=db_field_binding.dataset_schema_id
        )
        mock_uow.data_types.get.return_value = None

        with patch.object(
            field_binding_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await field_binding_service.update(
                    uow=mock_uow, obj_id=db_field_binding.id, obj_in=update_schema
                )
        assert exc_info.value.error_code == errors.DATA_TYPE_NOT_FOUND
