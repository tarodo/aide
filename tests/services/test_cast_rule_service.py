import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models import CastRule, DataType
from backend.schemas.cast_rule import CastRuleCreate, CastRuleUpdate
from backend.services.cast_rule import CastRuleService


class _MockRepository:
    def __init__(self) -> None:
        self.get_by_source_and_target_data_type_ids: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()
        self.create: AsyncMock = AsyncMock()
        self.update: AsyncMock = AsyncMock()


class _MockDataTypes:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.data_types = _MockDataTypes()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    return _MockUnitOfWork()


@pytest.fixture
def cast_rule_service() -> CastRuleService:
    return CastRuleService()


@pytest.fixture
def db_data_type1() -> DataType:
    return DataType(id=uuid.uuid4(), code="INT")


@pytest.fixture
def db_data_type2() -> DataType:
    return DataType(id=uuid.uuid4(), code="BIGINT")


@pytest.fixture
def cast_rule_create_schema(
    db_data_type1: DataType, db_data_type2: DataType
) -> CastRuleCreate:
    return CastRuleCreate(
        source_data_type_id=db_data_type1.id,
        target_data_type_id=db_data_type2.id,
        param_mapping={},
        safety="safe",
    )


@pytest.fixture
def db_cast_rule(cast_rule_create_schema: CastRuleCreate) -> CastRule:
    now = datetime.now(UTC)
    return CastRule(
        id=uuid.uuid4(),
        source_data_type_id=cast_rule_create_schema.source_data_type_id,
        target_data_type_id=cast_rule_create_schema.target_data_type_id,
        param_mapping=cast_rule_create_schema.param_mapping,
        safety=cast_rule_create_schema.safety,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
class TestCastRuleService:
    async def test_create_duplicate(
        self,
        cast_rule_service: CastRuleService,
        mock_uow: _MockUnitOfWork,
        cast_rule_create_schema: CastRuleCreate,
        db_cast_rule: CastRule,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_source_and_target_data_type_ids.return_value = db_cast_rule

        with patch.object(cast_rule_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await cast_rule_service.create(
                    uow=mock_uow, obj_in=cast_rule_create_schema
                )
        assert exc_info.value.error_code == errors.CAST_RULE_ALREADY_EXISTS

    async def test_create_source_data_type_not_found(
        self,
        cast_rule_service: CastRuleService,
        mock_uow: _MockUnitOfWork,
        cast_rule_create_schema: CastRuleCreate,
        db_data_type2: DataType,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_source_and_target_data_type_ids.return_value = None
        mock_uow.data_types.get.side_effect = [None, db_data_type2]

        with patch.object(cast_rule_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await cast_rule_service.create(
                    uow=mock_uow, obj_in=cast_rule_create_schema
                )
        assert exc_info.value.error_code == errors.DATA_TYPE_NOT_FOUND

    async def test_create_target_data_type_not_found(
        self,
        cast_rule_service: CastRuleService,
        mock_uow: _MockUnitOfWork,
        cast_rule_create_schema: CastRuleCreate,
        db_data_type1: DataType,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_source_and_target_data_type_ids.return_value = None
        mock_uow.data_types.get.side_effect = [db_data_type1, None]

        with patch.object(cast_rule_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await cast_rule_service.create(
                    uow=mock_uow, obj_in=cast_rule_create_schema
                )
        assert exc_info.value.error_code == errors.DATA_TYPE_NOT_FOUND

    async def test_update_duplicate(
        self,
        cast_rule_service: CastRuleService,
        mock_uow: _MockUnitOfWork,
        db_cast_rule: CastRule,
        db_data_type1: DataType,
        db_data_type2: DataType,
    ):
        # Use a different source data type to actually change it
        new_source_id = uuid.uuid4()
        new_source_data_type = DataType(id=new_source_id, code="TEXT")
        update_schema = CastRuleUpdate(source_data_type_id=new_source_id)
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_cast_rule
        # Return a different CastRule to simulate duplicate
        duplicate_rule = CastRule(id=uuid.uuid4())
        mock_repo.get_by_source_and_target_data_type_ids.return_value = duplicate_rule
        # Need to set up data_types.get for validation that happens after duplicate check
        mock_uow.data_types.get.side_effect = [new_source_data_type, db_data_type2]

        with patch.object(cast_rule_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await cast_rule_service.update(
                    uow=mock_uow, obj_id=db_cast_rule.id, obj_in=update_schema
                )
        assert exc_info.value.error_code == errors.CAST_RULE_ALREADY_EXISTS

    async def test_update_data_type_not_found(
        self,
        cast_rule_service: CastRuleService,
        mock_uow: _MockUnitOfWork,
        db_cast_rule: CastRule,
    ):
        new_target_id = uuid.uuid4()
        update_schema = CastRuleUpdate(target_data_type_id=new_target_id)
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_cast_rule
        mock_repo.get_by_source_and_target_data_type_ids.return_value = None
        mock_uow.data_types.get.side_effect = [
            DataType(id=db_cast_rule.source_data_type_id),
            None,
        ]

        with patch.object(cast_rule_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await cast_rule_service.update(
                    uow=mock_uow, obj_id=db_cast_rule.id, obj_in=update_schema
                )
        assert exc_info.value.error_code == errors.DATA_TYPE_NOT_FOUND
