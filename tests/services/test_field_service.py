import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from aide_schemas.field import FieldOrigin
from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.field import Field
from backend.schemas.field import FieldCreate, FieldUpdate
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


def _make_field(origin: str = "mapped") -> Field:
    now = datetime.now(UTC)
    return Field(
        id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        name="field_a",
        origin=origin,
        created_at=now,
        updated_at=now,
        row_version=1,
    )


@pytest.fixture
def db_field() -> Field:
    return _make_field(origin="mapped")


async def _run_pre_update(
    field_service: FieldService,
    mock_uow: _MockUnitOfWork,
    db_obj: Field,
    new_origin: FieldOrigin,
    inbound_link_count: int,
) -> None:
    """Invoke service.update() with a configured mock UoW/repo.

    ``uow.field_links.count_by_target_field`` returns ``inbound_link_count``.
    The repository mock is wired so row_version and name lookups pass cleanly.
    """
    mock_uow.field_links = AsyncMock()
    mock_uow.field_links.count_by_target_field = AsyncMock(
        return_value=inbound_link_count
    )
    mock_repo = _MockFieldRepo()
    mock_repo.get.return_value = db_obj
    mock_repo.get_by_dataset_and_name.return_value = None
    mock_repo.update.return_value = db_obj
    update = FieldUpdate(origin=new_origin, row_version=db_obj.row_version)
    with patch.object(field_service, "_get_repository", return_value=mock_repo):
        await field_service.update(uow=mock_uow, obj_id=db_obj.id, obj_in=update)


@pytest.mark.asyncio
async def test_origin_mapped_to_deprecated_blocked_by_field_link(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """MAPPED -> DEPRECATED requires zero inbound FieldLinks."""
    db_field = _make_field(origin="mapped")
    with pytest.raises(AppException) as exc:
        await _run_pre_update(
            field_service,
            mock_uow,
            db_field,
            FieldOrigin.DEPRECATED,
            inbound_link_count=2,
        )
    assert exc.value.error_code == errors.FIELD_ORIGIN_CONFLICT


@pytest.mark.asyncio
async def test_origin_mapped_to_tech_blocked_by_field_link(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """MAPPED -> TECH requires zero inbound FieldLinks."""
    db_field = _make_field(origin="mapped")
    with pytest.raises(AppException) as exc:
        await _run_pre_update(
            field_service,
            mock_uow,
            db_field,
            FieldOrigin.TECH,
            inbound_link_count=1,
        )
    assert exc.value.error_code == errors.FIELD_ORIGIN_CONFLICT


@pytest.mark.asyncio
async def test_origin_mapped_to_deprecated_allowed_when_unlinked(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """MAPPED -> DEPRECATED passes when no inbound FieldLinks."""
    db_field = _make_field(origin="mapped")
    await _run_pre_update(
        field_service,
        mock_uow,
        db_field,
        FieldOrigin.DEPRECATED,
        inbound_link_count=0,
    )


@pytest.mark.asyncio
async def test_origin_tech_to_mapped_blocked_without_field_link(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """TECH -> MAPPED requires at least one FieldLink already present."""
    db_field = _make_field(origin="tech")
    with pytest.raises(AppException) as exc:
        await _run_pre_update(
            field_service,
            mock_uow,
            db_field,
            FieldOrigin.MAPPED,
            inbound_link_count=0,
        )
    assert exc.value.error_code == errors.FIELD_ORIGIN_CONFLICT


@pytest.mark.asyncio
async def test_origin_tech_to_mapped_allowed_with_field_link(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """TECH -> MAPPED passes when FieldLink exists."""
    db_field = _make_field(origin="tech")
    await _run_pre_update(
        field_service,
        mock_uow,
        db_field,
        FieldOrigin.MAPPED,
        inbound_link_count=1,
    )


@pytest.mark.asyncio
async def test_origin_tech_to_deprecated_unconditional(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """TECH -> DEPRECATED: no condition, always allowed."""
    db_field = _make_field(origin="tech")
    # Even if blockers would be present, TECH -> DEPRECATED is unconditional.
    await _run_pre_update(
        field_service,
        mock_uow,
        db_field,
        FieldOrigin.DEPRECATED,
        inbound_link_count=5,
    )


@pytest.mark.asyncio
async def test_origin_deprecated_to_tech_unconditional(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """DEPRECATED -> TECH: no condition, always allowed."""
    db_field = _make_field(origin="deprecated")
    await _run_pre_update(
        field_service,
        mock_uow,
        db_field,
        FieldOrigin.TECH,
        inbound_link_count=3,
    )


@pytest.mark.asyncio
async def test_origin_deprecated_to_mapped_blocked_without_field_link(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """DEPRECATED -> MAPPED requires FieldLink existence."""
    db_field = _make_field(origin="deprecated")
    with pytest.raises(AppException) as exc:
        await _run_pre_update(
            field_service,
            mock_uow,
            db_field,
            FieldOrigin.MAPPED,
            inbound_link_count=0,
        )
    assert exc.value.error_code == errors.FIELD_ORIGIN_CONFLICT


@pytest.mark.asyncio
async def test_origin_deprecated_to_mapped_allowed_with_field_link(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """DEPRECATED -> MAPPED passes when FieldLink exists."""
    db_field = _make_field(origin="deprecated")
    await _run_pre_update(
        field_service,
        mock_uow,
        db_field,
        FieldOrigin.MAPPED,
        inbound_link_count=2,
    )


@pytest.mark.asyncio
async def test_pre_create_dataset_missing_raises(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    mock_uow.datasets.get = AsyncMock(return_value=None)
    obj_in = FieldCreate(dataset_id=uuid.uuid4(), name="x", origin="mapped")

    with pytest.raises(AppException) as exc:
        with patch.object(field_service, "_get_repository"):
            await field_service.create(uow=mock_uow, obj_in=obj_in)
    assert exc.value.error_code == errors.DATASET_NOT_FOUND


@pytest.mark.asyncio
async def test_pre_create_parent_missing_raises(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    mock_uow.datasets.get = AsyncMock(return_value=object())
    mock_uow.fields.get = AsyncMock(return_value=None)
    obj_in = FieldCreate(
        dataset_id=uuid.uuid4(),
        name="x",
        origin="mapped",
        parent_id=uuid.uuid4(),
    )

    with pytest.raises(AppException) as exc:
        with patch.object(field_service, "_get_repository"):
            await field_service.create(uow=mock_uow, obj_in=obj_in)
    assert exc.value.error_code == errors.FIELD_PARENT_NOT_FOUND


@pytest.mark.asyncio
async def test_pre_create_parent_dataset_mismatch_raises(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    mock_uow.datasets.get = AsyncMock(return_value=object())
    parent = _make_field()
    mock_uow.fields.get = AsyncMock(return_value=parent)

    obj_in = FieldCreate(
        dataset_id=uuid.uuid4(),  # different from parent.dataset_id
        name="x",
        origin="mapped",
        parent_id=parent.id,
    )

    with pytest.raises(AppException) as exc:
        with patch.object(field_service, "_get_repository"):
            await field_service.create(uow=mock_uow, obj_in=obj_in)
    assert exc.value.error_code == errors.FIELD_PARENT_DATASET_MISMATCH


@pytest.mark.asyncio
async def test_pre_create_duplicate_name_raises(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    mock_uow.datasets.get = AsyncMock(return_value=object())
    repo = _MockFieldRepo()
    repo.get_by_dataset_and_name.return_value = _make_field()  # collision

    obj_in = FieldCreate(dataset_id=uuid.uuid4(), name="dup", origin="mapped")
    with pytest.raises(AppException) as exc:
        with patch.object(field_service, "_get_repository", return_value=repo):
            await field_service.create(uow=mock_uow, obj_in=obj_in)
    assert exc.value.error_code == errors.FIELD_ALREADY_EXISTS


@pytest.mark.asyncio
async def test_circular_reference_self_assigned(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    me = _make_field()
    # new_parent_id == self.id -> immediate cycle
    with pytest.raises(AppException) as exc:
        await field_service._check_circular_reference(mock_uow, me.id, me.id)
    assert exc.value.error_code == errors.FIELD_CIRCULAR_REFERENCE


@pytest.mark.asyncio
async def test_circular_reference_via_ancestor(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """me -> child -> grandchild; assigning me.parent = grandchild forms a cycle."""
    me = _make_field()
    child = _make_field()
    grandchild = _make_field()
    child.parent_id = me.id
    grandchild.parent_id = child.id

    async def fake_get(field_id):
        if field_id == grandchild.id:
            return grandchild
        if field_id == child.id:
            return child
        if field_id == me.id:
            return me
        return None

    mock_uow.fields.get = AsyncMock(side_effect=fake_get)
    with pytest.raises(AppException) as exc:
        await field_service._check_circular_reference(mock_uow, me.id, grandchild.id)
    assert exc.value.error_code == errors.FIELD_CIRCULAR_REFERENCE


@pytest.mark.asyncio
async def test_circular_reference_breaks_on_visited_loop(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    """If the chain itself loops on a non-self id, walker terminates without raising."""
    me = _make_field()
    a = _make_field()
    b = _make_field()
    a.parent_id = b.id
    b.parent_id = a.id  # a<->b loop, neither is `me`

    async def fake_get(field_id):
        if field_id == a.id:
            return a
        if field_id == b.id:
            return b
        return None

    mock_uow.fields.get = AsyncMock(side_effect=fake_get)
    # Should NOT raise - `me` is not in the cycle.
    await field_service._check_circular_reference(mock_uow, me.id, a.id)


@pytest.mark.asyncio
async def test_get_tree_validates_dataset(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    mock_uow.datasets.get = AsyncMock(return_value=None)
    with pytest.raises(AppException) as exc:
        await field_service.get_tree(mock_uow, uuid.uuid4())
    assert exc.value.error_code == errors.DATASET_NOT_FOUND


@pytest.mark.asyncio
async def test_get_children_field_missing(
    field_service: FieldService, mock_uow: _MockUnitOfWork
):
    mock_uow.fields.get = AsyncMock(return_value=None)
    with pytest.raises(AppException) as exc:
        await field_service.get_children(mock_uow, uuid.uuid4())
    assert exc.value.error_code == errors.FIELD_NOT_FOUND
