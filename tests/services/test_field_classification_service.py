import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.schemas.field_classification import FieldClassificationCreate
from backend.services.field_classification import FieldClassificationService


class _MockRepository:
    def __init__(self) -> None:
        self.create: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()


class _MockFields:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.fields = _MockFields()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    return _MockUnitOfWork()


@pytest.mark.asyncio
async def test_create_fails_on_unknown_field(mock_uow: _MockUnitOfWork):
    mock_uow.fields.get.return_value = None
    service = FieldClassificationService()
    payload = FieldClassificationCreate(field_id=uuid.uuid4(), pii_tags=["email"])

    with pytest.raises(AppException) as exc:
        await service.create(uow=mock_uow, obj_in=payload, creator_id=None)
    assert exc.value.error_code == errors.FIELD_NOT_FOUND
