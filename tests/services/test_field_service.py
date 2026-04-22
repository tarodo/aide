import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.field import Field
from backend.schemas.field import FieldUpdate
from backend.services.field import FieldService


class _MockFieldRepo:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()
        self.get_by_dataset_and_name: AsyncMock = AsyncMock(return_value=None)
        self.get_children: AsyncMock = AsyncMock(return_value=[])
        self.get_roots: AsyncMock = AsyncMock(return_value=[])
        self.get_tree: AsyncMock = AsyncMock(return_value=[])
        self.create: AsyncMock = AsyncMock()
        self.update: AsyncMock = AsyncMock()
        self.delete: AsyncMock = AsyncMock()
        self.get_multi_paginated: AsyncMock = AsyncMock(return_value=([], 0))


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = AsyncMock()
        self.datasets = AsyncMock()
        self.fields = AsyncMock()
        self.field_links = AsyncMock()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    return _MockUnitOfWork()


@pytest.fixture
def field_service() -> FieldService:
    return FieldService()


@pytest.fixture
def db_field() -> Field:
    now = datetime.now(UTC)
    return Field(
        id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        name="field_a",
        is_tech=True,
        created_at=now,
        updated_at=now,
        row_version=1,
    )


@pytest.mark.asyncio
async def test_update_to_non_tech_requires_inbound_links(
    field_service: FieldService, mock_uow: _MockUnitOfWork, db_field: Field
):
    # db_field currently is_tech=True; update to is_tech=False with no inbound links -> reject
    db_field.is_tech = True
    mock_uow.field_links = AsyncMock()
    mock_uow.field_links.count_by_target_field = AsyncMock(return_value=0)
    mock_repo = _MockFieldRepo()
    mock_repo.get.return_value = db_field
    mock_repo.get_by_dataset_and_name.return_value = None
    update = FieldUpdate(is_tech=False, row_version=db_field.row_version)
    with patch.object(field_service, "_get_repository", return_value=mock_repo):
        with pytest.raises(AppException) as exc:
            await field_service.update(uow=mock_uow, obj_id=db_field.id, obj_in=update)
    assert exc.value.error_code == errors.FIELD_NON_TECH_REQUIRES_SOURCE


@pytest.mark.asyncio
async def test_update_to_non_tech_allowed_when_has_links(
    field_service: FieldService, mock_uow: _MockUnitOfWork, db_field: Field
):
    db_field.is_tech = True
    mock_uow.field_links = AsyncMock()
    mock_uow.field_links.count_by_target_field = AsyncMock(return_value=1)
    mock_repo = _MockFieldRepo()
    mock_repo.get.return_value = db_field
    mock_repo.get_by_dataset_and_name.return_value = None
    mock_repo.update.return_value = db_field
    update = FieldUpdate(is_tech=False, row_version=db_field.row_version)
    with patch.object(field_service, "_get_repository", return_value=mock_repo):
        await field_service.update(uow=mock_uow, obj_id=db_field.id, obj_in=update)
