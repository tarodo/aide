import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.dataset_link import DatasetLink
from backend.models.dataset import DatasetRdbms
from backend.schemas.dataset_link import (
    DatasetLinkCreate,
    DatasetLinkRead,
)
from backend.services.dataset_link import DatasetLinkService


class _MockRepo:
    def __init__(self) -> None:
        self.get = AsyncMock()
        self.get_including_deleted = AsyncMock()
        self.get_active_between = AsyncMock(return_value=None)
        self.has_active_links_for_dataset = AsyncMock(return_value=False)
        self.list_by_source = AsyncMock(return_value=[])
        self.list_by_target = AsyncMock(return_value=[])
        self.create = AsyncMock()
        self.update = AsyncMock()
        self.delete = AsyncMock()
        self.restore = AsyncMock()
        self.get_multi_paginated = AsyncMock(return_value=([], 0))


class _MockUoW:
    def __init__(self) -> None:
        self.session = AsyncMock()
        self.datasets = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def _ds(layer: str | None, sys_id: uuid.UUID | None = None) -> DatasetRdbms:
    return DatasetRdbms(
        id=uuid.uuid4(),
        system_id=sys_id or uuid.uuid4(),
        object_name="o",
        kind="rdbms",
        schema_name="s",
        table_name="t",
        layer=layer,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        row_version=1,
    )


@pytest.fixture
def service() -> DatasetLinkService:
    return DatasetLinkService()


@pytest.mark.asyncio
class TestDatasetLinkService:
    async def test_create_happy_path(self, service: DatasetLinkService):
        src = _ds("source")
        tgt = _ds("raw")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        created = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        repo.create.return_value = created

        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=DatasetLinkCreate(
                    source_dataset_id=src.id, target_dataset_id=tgt.id
                ),
            )
        assert isinstance(result, DatasetLinkRead)
        assert result.source_dataset_id == src.id
        assert result.target_dataset_id == tgt.id

    async def test_create_self_link_rejected(self, service: DatasetLinkService):
        ds = _ds("source")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [ds, ds]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=ds.id, target_dataset_id=ds.id
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_LINK_SELF_REFERENCE

    async def test_create_source_not_found(self, service: DatasetLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        uow = _MockUoW()
        uow.datasets.get.side_effect = [None, _ds("raw")]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src_id, target_dataset_id=tgt_id
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_NOT_FOUND

    async def test_create_layer_missing(self, service: DatasetLinkService):
        src = _ds(None)
        tgt = _ds("raw")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id, target_dataset_id=tgt.id
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_LINK_LAYER_MISSING

    async def test_create_layer_order_violated(self, service: DatasetLinkService):
        src = _ds("core")
        tgt = _ds("raw")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id, target_dataset_id=tgt.id
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_LINK_LAYER_ORDER

    async def test_create_skip_layer_allowed(self, service: DatasetLinkService):
        """Source->Raw skipping CDC/Kafka must succeed."""
        src = _ds("source")
        tgt = _ds("raw")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        repo.create.return_value = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            await service.create(
                uow=uow,
                obj_in=DatasetLinkCreate(
                    source_dataset_id=src.id, target_dataset_id=tgt.id
                ),
            )

    async def test_create_cross_system_allowed(self, service: DatasetLinkService):
        sys_a, sys_b = uuid.uuid4(), uuid.uuid4()
        src = _ds("kafka", sys_a)
        tgt = _ds("raw", sys_b)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        repo.create.return_value = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            await service.create(
                uow=uow,
                obj_in=DatasetLinkCreate(
                    source_dataset_id=src.id, target_dataset_id=tgt.id
                ),
            )

    async def test_create_duplicate_active(self, service: DatasetLinkService):
        src = _ds("source")
        tgt = _ds("raw")
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        repo = _MockRepo()
        repo.get_active_between.return_value = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id, target_dataset_id=tgt.id
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_LINK_ALREADY_EXISTS
