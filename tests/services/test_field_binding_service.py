import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models import DatasetSchema, Field, FieldBinding, TypeInstance
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


class _MockTypeInstances:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.fields = _MockFields()
        self.dataset_schemas = _MockDatasetSchemas()
        self.type_instances = _MockTypeInstances()

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
    return Field(id=uuid.uuid4(), name="id", row_version=1)


@pytest.fixture
def db_dataset_schema() -> DatasetSchema:
    return DatasetSchema(id=uuid.uuid4(), version_num=1, row_version=1)


@pytest.fixture
def db_type_instance() -> TypeInstance:
    return TypeInstance(id=uuid.uuid4(), data_type_id=uuid.uuid4(), row_version=1)


@pytest.fixture
def field_binding_create_schema(
    db_field: Field, db_dataset_schema: DatasetSchema, db_type_instance: TypeInstance
) -> FieldBindingCreate:
    return FieldBindingCreate(
        field_id=db_field.id,
        dataset_schema_id=db_dataset_schema.id,
        position=1,
        is_nullable=False,
        type_instance_id=db_type_instance.id,
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
        type_instance_id=field_binding_create_schema.type_instance_id,
        created_at=now,
        updated_at=now,
        row_version=1,
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
            ("type_instance", errors.TYPE_INSTANCE_NOT_FOUND),
        ],
    )
    async def test_create_dependency_not_found(
        self,
        field_binding_service: FieldBindingService,
        mock_uow: _MockUnitOfWork,
        field_binding_create_schema: FieldBindingCreate,
        db_field: Field,
        db_dataset_schema: DatasetSchema,
        db_type_instance: TypeInstance,
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
        mock_uow.type_instances.get.return_value = (
            None if missing_entity == "type_instance" else db_type_instance
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
        update_schema = FieldBindingUpdate(field_id=uuid.uuid4(), row_version=1)
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_field_binding
        mock_repo.get_by_dataset_schema_and_field_id.return_value = FieldBinding(
            id=uuid.uuid4(), row_version=1
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
        update_schema = FieldBindingUpdate(position=99, row_version=1)
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_field_binding
        mock_repo.get_by_dataset_schema_and_field_id.return_value = None
        mock_repo.get_by_dataset_schema_and_position.return_value = FieldBinding(
            id=uuid.uuid4(), row_version=1
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
        update_schema = FieldBindingUpdate(type_instance_id=uuid.uuid4(), row_version=1)
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_field_binding
        mock_repo.get_by_dataset_schema_and_field_id.return_value = None
        mock_repo.get_by_dataset_schema_and_position.return_value = None
        mock_uow.fields.get.return_value = Field(
            id=db_field_binding.field_id, row_version=1
        )
        mock_uow.dataset_schemas.get.return_value = DatasetSchema(
            id=db_field_binding.dataset_schema_id, row_version=1
        )
        mock_uow.type_instances.get.return_value = None

        with patch.object(
            field_binding_service, "_get_repository", return_value=mock_repo
        ):
            with pytest.raises(AppException) as exc_info:
                await field_binding_service.update(
                    uow=mock_uow, obj_id=db_field_binding.id, obj_in=update_schema
                )
        assert exc_info.value.error_code == errors.TYPE_INSTANCE_NOT_FOUND
