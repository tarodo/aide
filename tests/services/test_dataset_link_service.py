import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.dataset import DatasetRdbms
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.schemas.dataset_link import (
    DatasetLinkCreate,
    DatasetLinkRead,
    DatasetLinkUpdate,
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
        self.dataset_schemas = AsyncMock()

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


def _schema(dataset_id: uuid.UUID, version_num: int = 1) -> DatasetSchema:
    now = datetime.now(UTC)
    return DatasetSchema(
        id=uuid.uuid4(),
        dataset_id=dataset_id,
        version_num=version_num,
        schema=None,
        extra=None,
        created_at=now,
        updated_at=now,
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
        src_schema = _schema(src.id)
        tgt_schema = _schema(tgt.id)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        uow.dataset_schemas.get.side_effect = [src_schema, tgt_schema]
        repo = _MockRepo()
        created = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            source_schema_id=src_schema.id,
            target_schema_id=tgt_schema.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        repo.create.return_value = created

        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=DatasetLinkCreate(
                    source_dataset_id=src.id,
                    target_dataset_id=tgt.id,
                    source_schema_id=src_schema.id,
                    target_schema_id=tgt_schema.id,
                ),
            )
        assert isinstance(result, DatasetLinkRead)
        assert result.source_dataset_id == src.id
        assert result.target_dataset_id == tgt.id
        assert result.source_schema_id == src_schema.id
        assert result.target_schema_id == tgt_schema.id

    async def test_create_self_link_rejected(self, service: DatasetLinkService):
        ds = _ds("source")
        schema = _schema(ds.id)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [ds, ds]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=ds.id,
                        target_dataset_id=ds.id,
                        source_schema_id=schema.id,
                        target_schema_id=schema.id,
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
                        source_dataset_id=src_id,
                        target_dataset_id=tgt_id,
                        source_schema_id=uuid.uuid4(),
                        target_schema_id=uuid.uuid4(),
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
                        source_dataset_id=src.id,
                        target_dataset_id=tgt.id,
                        source_schema_id=uuid.uuid4(),
                        target_schema_id=uuid.uuid4(),
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
                        source_dataset_id=src.id,
                        target_dataset_id=tgt.id,
                        source_schema_id=uuid.uuid4(),
                        target_schema_id=uuid.uuid4(),
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_LINK_LAYER_ORDER

    async def test_create_skip_layer_allowed(self, service: DatasetLinkService):
        """Source->Raw skipping CDC/Kafka must succeed."""
        src = _ds("source")
        tgt = _ds("raw")
        src_schema = _schema(src.id)
        tgt_schema = _schema(tgt.id)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        uow.dataset_schemas.get.side_effect = [src_schema, tgt_schema]
        repo = _MockRepo()
        repo.create.return_value = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            source_schema_id=src_schema.id,
            target_schema_id=tgt_schema.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            await service.create(
                uow=uow,
                obj_in=DatasetLinkCreate(
                    source_dataset_id=src.id,
                    target_dataset_id=tgt.id,
                    source_schema_id=src_schema.id,
                    target_schema_id=tgt_schema.id,
                ),
            )

    async def test_create_cross_system_allowed(self, service: DatasetLinkService):
        sys_a, sys_b = uuid.uuid4(), uuid.uuid4()
        src = _ds("kafka", sys_a)
        tgt = _ds("raw", sys_b)
        src_schema = _schema(src.id)
        tgt_schema = _schema(tgt.id)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        uow.dataset_schemas.get.side_effect = [src_schema, tgt_schema]
        repo = _MockRepo()
        repo.create.return_value = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            source_schema_id=src_schema.id,
            target_schema_id=tgt_schema.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            await service.create(
                uow=uow,
                obj_in=DatasetLinkCreate(
                    source_dataset_id=src.id,
                    target_dataset_id=tgt.id,
                    source_schema_id=src_schema.id,
                    target_schema_id=tgt_schema.id,
                ),
            )

    async def test_create_duplicate_active(self, service: DatasetLinkService):
        src = _ds("source")
        tgt = _ds("raw")
        src_schema = _schema(src.id)
        tgt_schema = _schema(tgt.id)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        uow.dataset_schemas.get.side_effect = [src_schema, tgt_schema]
        repo = _MockRepo()
        repo.get_active_between.return_value = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            source_schema_id=src_schema.id,
            target_schema_id=tgt_schema.id,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id,
                        target_dataset_id=tgt.id,
                        source_schema_id=src_schema.id,
                        target_schema_id=tgt_schema.id,
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_LINK_ALREADY_EXISTS

    # --- Schema pin validation (Task 13) ---

    async def test_create_rejects_source_schema_mismatch(
        self, service: DatasetLinkService
    ):
        """source_schema.dataset_id != source_dataset_id → SCHEMA_DATASET_MISMATCH"""
        src = _ds("source")
        tgt = _ds("raw")
        # Source schema belongs to a different dataset
        wrong_src_schema = _schema(uuid.uuid4())
        tgt_schema = _schema(tgt.id)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        uow.dataset_schemas.get.side_effect = [wrong_src_schema, tgt_schema]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id,
                        target_dataset_id=tgt.id,
                        source_schema_id=wrong_src_schema.id,
                        target_schema_id=tgt_schema.id,
                    ),
                )
        assert exc_info.value.error_code == errors.SCHEMA_DATASET_MISMATCH

    async def test_create_rejects_target_schema_mismatch(
        self, service: DatasetLinkService
    ):
        """target_schema.dataset_id != target_dataset_id → SCHEMA_DATASET_MISMATCH"""
        src = _ds("source")
        tgt = _ds("raw")
        src_schema = _schema(src.id)
        # Target schema belongs to a different dataset
        wrong_tgt_schema = _schema(uuid.uuid4())
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        uow.dataset_schemas.get.side_effect = [src_schema, wrong_tgt_schema]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id,
                        target_dataset_id=tgt.id,
                        source_schema_id=src_schema.id,
                        target_schema_id=wrong_tgt_schema.id,
                    ),
                )
        assert exc_info.value.error_code == errors.SCHEMA_DATASET_MISMATCH

    async def test_create_rejects_missing_source_schema(
        self, service: DatasetLinkService
    ):
        """source schema id doesn't exist → DATASET_SCHEMA_NOT_FOUND"""
        src = _ds("source")
        tgt = _ds("raw")
        tgt_schema = _schema(tgt.id)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        uow.dataset_schemas.get.side_effect = [None, tgt_schema]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id,
                        target_dataset_id=tgt.id,
                        source_schema_id=uuid.uuid4(),
                        target_schema_id=tgt_schema.id,
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_SCHEMA_NOT_FOUND

    async def test_create_rejects_missing_target_schema(
        self, service: DatasetLinkService
    ):
        """target schema id doesn't exist → DATASET_SCHEMA_NOT_FOUND"""
        src = _ds("source")
        tgt = _ds("raw")
        src_schema = _schema(src.id)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        uow.dataset_schemas.get.side_effect = [src_schema, None]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.create(
                    uow=uow,
                    obj_in=DatasetLinkCreate(
                        source_dataset_id=src.id,
                        target_dataset_id=tgt.id,
                        source_schema_id=src_schema.id,
                        target_schema_id=uuid.uuid4(),
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_SCHEMA_NOT_FOUND

    async def test_create_passes_when_both_schemas_match(
        self, service: DatasetLinkService
    ):
        """Happy path: both schemas belong to correct datasets."""
        src = _ds("source")
        tgt = _ds("raw")
        src_schema = _schema(src.id)
        tgt_schema = _schema(tgt.id)
        uow = _MockUoW()
        uow.datasets.get.side_effect = [src, tgt]
        uow.dataset_schemas.get.side_effect = [src_schema, tgt_schema]
        repo = _MockRepo()
        repo.create.return_value = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            source_schema_id=src_schema.id,
            target_schema_id=tgt_schema.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=DatasetLinkCreate(
                    source_dataset_id=src.id,
                    target_dataset_id=tgt.id,
                    source_schema_id=src_schema.id,
                    target_schema_id=tgt_schema.id,
                ),
            )
        assert result.source_schema_id == src_schema.id
        assert result.target_schema_id == tgt_schema.id

    async def test_update_rejects_source_schema_mismatch(
        self, service: DatasetLinkService
    ):
        """PATCH source_schema_id to a schema of a different dataset → SCHEMA_DATASET_MISMATCH"""
        src = _ds("source")
        tgt = _ds("raw")
        original_src_schema = _schema(src.id)
        original_tgt_schema = _schema(tgt.id)
        db_link = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            source_schema_id=original_src_schema.id,
            target_schema_id=original_tgt_schema.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        # Candidate new source schema belongs to a different dataset
        bad_schema = _schema(uuid.uuid4())
        uow = _MockUoW()
        uow.dataset_schemas.get.return_value = bad_schema
        repo = _MockRepo()
        repo.get.return_value = db_link
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.update(
                    uow=uow,
                    obj_id=db_link.id,
                    obj_in=DatasetLinkUpdate(
                        source_schema_id=bad_schema.id, row_version=1
                    ),
                )
        assert exc_info.value.error_code == errors.SCHEMA_DATASET_MISMATCH

    async def test_update_passes_when_schema_matches(self, service: DatasetLinkService):
        """Happy path for update."""
        src = _ds("source")
        tgt = _ds("raw")
        original_src_schema = _schema(src.id, version_num=1)
        original_tgt_schema = _schema(tgt.id, version_num=1)
        new_src_schema = _schema(src.id, version_num=2)
        db_link = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            source_schema_id=original_src_schema.id,
            target_schema_id=original_tgt_schema.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        uow = _MockUoW()
        uow.dataset_schemas.get.return_value = new_src_schema
        repo = _MockRepo()
        repo.get.return_value = db_link
        updated_link = DatasetLink(
            id=db_link.id,
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            source_schema_id=new_src_schema.id,
            target_schema_id=original_tgt_schema.id,
            created_at=db_link.created_at,
            updated_at=datetime.now(UTC),
            row_version=2,
        )
        repo.update.return_value = updated_link
        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.update(
                uow=uow,
                obj_id=db_link.id,
                obj_in=DatasetLinkUpdate(
                    source_schema_id=new_src_schema.id, row_version=1
                ),
            )
        assert result.source_schema_id == new_src_schema.id

    async def test_update_schema_missing_returns_not_found(
        self, service: DatasetLinkService
    ):
        """PATCH with nonexistent schema_id → DATASET_SCHEMA_NOT_FOUND"""
        src = _ds("source")
        tgt = _ds("raw")
        original_src_schema = _schema(src.id)
        original_tgt_schema = _schema(tgt.id)
        db_link = DatasetLink(
            id=uuid.uuid4(),
            source_dataset_id=src.id,
            target_dataset_id=tgt.id,
            source_schema_id=original_src_schema.id,
            target_schema_id=original_tgt_schema.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        uow = _MockUoW()
        uow.dataset_schemas.get.return_value = None
        repo = _MockRepo()
        repo.get.return_value = db_link
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc_info:
                await service.update(
                    uow=uow,
                    obj_id=db_link.id,
                    obj_in=DatasetLinkUpdate(
                        target_schema_id=uuid.uuid4(), row_version=1
                    ),
                )
        assert exc_info.value.error_code == errors.DATASET_SCHEMA_NOT_FOUND
