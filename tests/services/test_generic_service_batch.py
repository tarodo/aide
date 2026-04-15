import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from backend.models.system_kind import SystemKind
from backend.schemas.batch import BatchCreateRequest, BatchCreateResponse
from backend.schemas.system_kind import SystemKindCreate, SystemKindRead
from backend.services.system_kind import SystemKindService


class _Item(BaseModel):
    name: str


def test_batch_request_requires_nonempty_items():
    from pydantic import ValidationError

    BatchCreateRequest[_Item].model_validate({"items": [{"name": "a"}]})

    with pytest.raises(ValidationError):
        BatchCreateRequest[_Item].model_validate({"items": []})


def test_batch_response_shape():
    resp = BatchCreateResponse[_Item].model_validate(
        {"items": [{"name": "a"}, {"name": "b"}], "count": 2}
    )
    assert resp.count == 2
    assert [i.name for i in resp.items] == ["a", "b"]


# ---------------------------------------------------------------------------
# Service-level unit tests for GenericService.create_many
# ---------------------------------------------------------------------------


class _MockRepository:
    def __init__(self) -> None:
        self.create_many: AsyncMock = AsyncMock()
        self.get_by_code: AsyncMock = AsyncMock(return_value=None)
        self.get: AsyncMock = AsyncMock()
        self.create: AsyncMock = AsyncMock()
        self.update: AsyncMock = AsyncMock()
        self.delete: AsyncMock = AsyncMock()
        self.restore: AsyncMock = AsyncMock()
        self.get_including_deleted: AsyncMock = AsyncMock()
        self.get_multi_paginated: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        self.session.execute.return_value = mock_result

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


def _db_kind(code: str, creator_id: uuid.UUID) -> SystemKind:
    now = datetime.now(UTC)
    return SystemKind(
        id=uuid.uuid4(),
        code=code,
        name=f"Name {code}",
        created_by=creator_id,
        updated_by=creator_id,
        created_at=now,
        updated_at=now,
        row_version=1,
    )


@pytest.fixture
def service() -> SystemKindService:
    return SystemKindService()


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    return _MockUnitOfWork()


@pytest.mark.asyncio
async def test_create_many_empty_returns_empty_no_repo_call(
    service: SystemKindService, mock_uow: _MockUnitOfWork
):
    mock_repo = _MockRepository()
    with patch.object(service, "_get_repository", return_value=mock_repo):
        result = await service.create_many(mock_uow, items=[], creator_id=uuid.uuid4())
    assert result == []
    mock_repo.create_many.assert_not_called()


@pytest.mark.asyncio
async def test_create_many_calls_repo_and_returns_reads(
    service: SystemKindService, mock_uow: _MockUnitOfWork
):
    creator_id = uuid.uuid4()
    items = [
        SystemKindCreate(code="BATCH_A", name="Name BATCH_A"),
        SystemKindCreate(code="BATCH_B", name="Name BATCH_B"),
    ]
    returned = [_db_kind("BATCH_A", creator_id), _db_kind("BATCH_B", creator_id)]

    mock_repo = _MockRepository()
    mock_repo.create_many.return_value = returned

    with patch.object(service, "_get_repository", return_value=mock_repo):
        result = await service.create_many(mock_uow, items=items, creator_id=creator_id)

    # Repo called once with the two db objects in order
    mock_repo.create_many.assert_awaited_once()
    _, kwargs = mock_repo.create_many.call_args
    db_objs = kwargs["objs"]
    assert len(db_objs) == 2
    assert [o.code for o in db_objs] == ["BATCH_A", "BATCH_B"]
    # created_by populated from creator_id
    for o in db_objs:
        assert o.created_by == creator_id
        assert o.updated_by == creator_id

    # Result contains read schemas in order
    assert [r.code for r in result] == ["BATCH_A", "BATCH_B"]
    assert all(isinstance(r, SystemKindRead) for r in result)
