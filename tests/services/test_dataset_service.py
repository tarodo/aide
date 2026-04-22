import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models import System
from backend.models.dataset import Dataset, DatasetKafka, DatasetRdbms
from backend.schemas.dataset import (
    DatasetKafkaCreate,
    DatasetKafkaUpdate,
    DatasetRdbmsCreate,
    DatasetRdbmsUpdate,
)
from backend.schemas.pagination import Page
from backend.services.dataset import DatasetService


class _MockRepository:
    def __init__(self) -> None:
        self.get_by_system_and_object_name: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()
        self.create: AsyncMock = AsyncMock()
        self.update: AsyncMock = AsyncMock()
        self.delete: AsyncMock = AsyncMock()
        self.restore: AsyncMock = AsyncMock()
        self.get_including_deleted: AsyncMock = AsyncMock()
        self.get_multi_paginated: AsyncMock = AsyncMock()


class _MockSystems:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockDatasetLinks:
    def __init__(self) -> None:
        self.has_active_links_for_dataset: AsyncMock = AsyncMock(return_value=False)


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.systems = _MockSystems()
        self.dataset_links = _MockDatasetLinks()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    return _MockUnitOfWork()


@pytest.fixture
def dataset_service() -> DatasetService:
    return DatasetService()


@pytest.fixture
def db_system() -> System:
    return System(id=uuid.uuid4(), code="SYS1", name="System 1", row_version=1)


@pytest.fixture
def rdbms_create_schema(db_system: System) -> DatasetRdbmsCreate:
    return DatasetRdbmsCreate(
        kind="rdbms",
        system_id=db_system.id,
        object_name="customers",
        schema_name="public",
        table_name="customers",
    )


@pytest.fixture
def kafka_create_schema(db_system: System) -> DatasetKafkaCreate:
    return DatasetKafkaCreate(
        kind="kafka",
        system_id=db_system.id,
        object_name="orders",
        topic="orders_topic",
        format="json",
        partitions=3,
        retention_ms=86400000,
        key_columns=["order_id"],
    )


@pytest.fixture
def db_dataset_rdbms(rdbms_create_schema: DatasetRdbmsCreate) -> DatasetRdbms:
    now = datetime.now(UTC)
    return DatasetRdbms(
        id=uuid.uuid4(),
        kind="rdbms",
        system_id=rdbms_create_schema.system_id,
        object_name=rdbms_create_schema.object_name,
        schema_name=rdbms_create_schema.schema_name,
        table_name=rdbms_create_schema.table_name,
        created_at=now,
        updated_at=now,
        is_active=True,
        row_version=1,
    )


@pytest.mark.asyncio
class TestDatasetService:
    async def test_create_rdbms_dataset_success(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        rdbms_create_schema: DatasetRdbmsCreate,
        db_dataset_rdbms: DatasetRdbms,
        db_system: System,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_system_and_object_name.return_value = None
        mock_repo.create.return_value = db_dataset_rdbms
        mock_uow.systems.get.return_value = db_system
        creator_id = uuid.uuid4()

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            result = await dataset_service.create(
                uow=mock_uow, obj_in=rdbms_create_schema, creator_id=creator_id
            )

        assert result.kind == "rdbms"

    async def test_create_kafka_dataset_success(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        kafka_create_schema: DatasetKafkaCreate,
        db_system: System,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_system_and_object_name.return_value = None
        now = datetime.now(UTC)
        db_dataset_kafka = DatasetKafka(
            id=uuid.uuid4(),
            kind="kafka",
            system_id=kafka_create_schema.system_id,
            object_name=kafka_create_schema.object_name,
            topic=kafka_create_schema.topic,
            format=kafka_create_schema.format,
            partitions=kafka_create_schema.partitions,
            retention_ms=kafka_create_schema.retention_ms,
            key_columns=kafka_create_schema.key_columns,
            created_at=now,
            updated_at=now,
            is_active=True,
            row_version=1,
        )
        mock_repo.create.return_value = db_dataset_kafka
        mock_uow.systems.get.return_value = db_system

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            result = await dataset_service.create(
                uow=mock_uow, obj_in=kafka_create_schema, creator_id=uuid.uuid4()
            )

        assert result.kind == "kafka"

    async def test_create_dataset_already_exists(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        rdbms_create_schema: DatasetRdbmsCreate,
        db_dataset_rdbms: DatasetRdbms,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_system_and_object_name.return_value = db_dataset_rdbms

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await dataset_service.create(
                    uow=mock_uow, obj_in=rdbms_create_schema, creator_id=uuid.uuid4()
                )
        assert exc_info.value.error_code == errors.DATASET_ALREADY_EXISTS

    async def test_create_dataset_system_not_found(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        rdbms_create_schema: DatasetRdbmsCreate,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_system_and_object_name.return_value = None
        mock_uow.systems.get.return_value = None

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await dataset_service.create(
                    uow=mock_uow, obj_in=rdbms_create_schema, creator_id=uuid.uuid4()
                )
        assert exc_info.value.error_code == errors.SYSTEM_NOT_FOUND

    async def test_create_invalid_kind(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_system: System,
        rdbms_create_schema: DatasetRdbmsCreate,
    ):
        invalid_schema = rdbms_create_schema.model_copy()
        invalid_schema.kind = "invalid_kind"
        mock_repo = _MockRepository()
        mock_repo.get_by_system_and_object_name.return_value = None
        mock_uow.systems.get.return_value = db_system

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await dataset_service.create(uow=mock_uow, obj_in=invalid_schema)
        assert exc_info.value.error_code == errors.INVALID_DATASET_KIND

    async def test_get_not_found(
        self, dataset_service: DatasetService, mock_uow: _MockUnitOfWork
    ):
        mock_repo = _MockRepository()
        mock_repo.get.return_value = None
        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await dataset_service.get_by_id(uow=mock_uow, obj_id=uuid.uuid4())
        assert exc_info.value.error_code == errors.DATASET_NOT_FOUND

    async def test_get_paginated(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms: DatasetRdbms,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_multi_paginated.return_value = ([db_dataset_rdbms], 1)
        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            result = await dataset_service.get_paginated(uow=mock_uow, page=1, size=10)
        assert isinstance(result, Page)
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].id == db_dataset_rdbms.id

    async def test_update_not_found(
        self, dataset_service: DatasetService, mock_uow: _MockUnitOfWork
    ):
        update_schema = DatasetRdbmsUpdate(kind="rdbms", layer="core", row_version=1)
        mock_repo = _MockRepository()
        mock_repo.get.return_value = None
        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await dataset_service.update(
                    uow=mock_uow, obj_id=uuid.uuid4(), obj_in=update_schema
                )
        assert exc_info.value.error_code == errors.DATASET_NOT_FOUND

    async def test_update_dataset_kind_mismatch(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms: DatasetRdbms,
    ):
        update_schema = DatasetKafkaUpdate(
            kind="kafka", topic="some_topic", row_version=1
        )
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_dataset_rdbms

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await dataset_service.update(
                    uow=mock_uow,
                    obj_id=db_dataset_rdbms.id,
                    obj_in=update_schema,
                    updater_id=uuid.uuid4(),
                )
        assert exc_info.value.error_code == errors.DATASET_KIND_MISMATCH

    async def test_pre_update_duplicate_object_name(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms: DatasetRdbms,
    ):
        update_schema = DatasetRdbmsUpdate(
            kind="rdbms", object_name="new_name", row_version=1
        )
        mock_repo = _MockRepository()
        mock_repo.get_by_system_and_object_name.return_value = Dataset(
            id=uuid.uuid4(), row_version=1
        )

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await dataset_service._pre_update(
                    uow=mock_uow,
                    db_obj=db_dataset_rdbms,
                    obj_in=update_schema,
                    updater_id=None,
                )
        assert exc_info.value.error_code == errors.DATASET_ALREADY_EXISTS

    async def test_delete_dataset_success(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms: DatasetRdbms,
    ):
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_dataset_rdbms
        mock_repo.delete.return_value = db_dataset_rdbms

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            result = await dataset_service.delete(
                uow=mock_uow, obj_id=db_dataset_rdbms.id
            )

        mock_repo.delete.assert_awaited_once_with(db_obj=db_dataset_rdbms)
        assert result.id == db_dataset_rdbms.id

    async def test_delete_sets_deleter_id(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms: DatasetRdbms,
    ):
        deleter_id = uuid.uuid4()
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_dataset_rdbms
        mock_repo.delete.return_value = db_dataset_rdbms

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            await dataset_service.delete(
                uow=mock_uow, obj_id=db_dataset_rdbms.id, deleter_id=deleter_id
            )

        assert db_dataset_rdbms.deleted_by == deleter_id

    async def test_delete_not_found(
        self, dataset_service: DatasetService, mock_uow: _MockUnitOfWork
    ):
        mock_repo = _MockRepository()
        mock_repo.get.return_value = None
        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await dataset_service.delete(uow=mock_uow, obj_id=uuid.uuid4())
        assert exc_info.value.error_code == errors.DATASET_NOT_FOUND

    async def test_delete_blocked_when_has_active_dataset_links(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms: DatasetRdbms,
    ):
        mock_uow.dataset_links.has_active_links_for_dataset = AsyncMock(
            return_value=True
        )
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_dataset_rdbms

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await dataset_service.delete(uow=mock_uow, obj_id=db_dataset_rdbms.id)
        assert exc_info.value.error_code == errors.DATASET_HAS_ACTIVE_LINKS
        mock_repo.delete.assert_not_awaited()
        mock_uow.dataset_links.has_active_links_for_dataset.assert_awaited_once_with(
            db_dataset_rdbms.id
        )

    async def test_restore_success(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms: DatasetRdbms,
    ):
        db_dataset_rdbms.deleted_at = datetime.now(UTC)
        mock_repo = _MockRepository()
        mock_repo.get_including_deleted.return_value = db_dataset_rdbms
        mock_repo.restore.return_value = db_dataset_rdbms

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            result = await dataset_service.restore(
                uow=mock_uow, obj_id=db_dataset_rdbms.id, restorer_id=uuid.uuid4()
            )

        mock_repo.restore.assert_awaited_once_with(db_obj=db_dataset_rdbms)
        assert result.id == db_dataset_rdbms.id

    async def test_restore_not_deleted_raises(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms: DatasetRdbms,
    ):
        db_dataset_rdbms.deleted_at = None
        mock_repo = _MockRepository()
        mock_repo.get_including_deleted.return_value = db_dataset_rdbms

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await dataset_service.restore(uow=mock_uow, obj_id=db_dataset_rdbms.id)
        assert exc_info.value.error_code == errors.ENTITY_NOT_DELETED

    async def test_apply_tech_template_happy(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms,
        db_system,
    ):
        from backend.models.data_type import DataType
        from backend.models.system_flavor import SystemFlavor
        from backend.models.tech_field_template import (
            TechFieldTemplate,
            TechFieldTemplateField,
        )

        db_dataset_rdbms.layer = "core"
        template = TechFieldTemplate(
            id=uuid.uuid4(), code="scd2", name="SCD2", layer="core"
        )
        tpl_field = TechFieldTemplateField(
            id=uuid.uuid4(),
            template_id=template.id,
            name="valid_from",
            type_code="TIMESTAMP",
            order=0,
        )
        flavor = SystemFlavor(
            id=uuid.uuid4(), code="postgres14", name="PG14", kind_id=uuid.uuid4()
        )
        db_system.flavor_id = flavor.id
        data_type = DataType(
            id=uuid.uuid4(),
            system_flavor_id=flavor.id,
            code="timestamp",
            params_schema={},
        )

        mock_uow.tech_field_templates = MagicMock()
        mock_uow.tech_field_templates.get = AsyncMock(return_value=template)
        mock_uow.tech_field_template_fields = MagicMock()
        mock_uow.tech_field_template_fields.list_by_template = AsyncMock(
            return_value=[tpl_field]
        )
        mock_uow.system_flavors = MagicMock()
        mock_uow.system_flavors.get = AsyncMock(return_value=flavor)
        mock_uow.data_types = MagicMock()
        mock_uow.data_types.get_by_system_flavor_and_code = AsyncMock(
            return_value=data_type
        )
        mock_uow.systems.get = AsyncMock(return_value=db_system)
        mock_uow.fields = MagicMock()
        mock_uow.fields.get_roots = AsyncMock(return_value=[])

        def _hydrate(objs):
            now = datetime.now(UTC)
            for o in objs:
                if getattr(o, "id", None) is None:
                    o.id = uuid.uuid4()
                if getattr(o, "created_at", None) is None:
                    o.created_at = now
                if getattr(o, "updated_at", None) is None:
                    o.updated_at = now
                if getattr(o, "row_version", None) is None:
                    o.row_version = 1
            return objs

        mock_uow.fields.create_many = AsyncMock(side_effect=_hydrate)

        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_dataset_rdbms
        fake_resolver = MagicMock()
        fake_resolver.resolve.return_value = "timestamp"
        with (
            patch.object(dataset_service, "_get_repository", return_value=mock_repo),
            patch("backend.services.dataset.tech_type_resolver", new=fake_resolver),
        ):
            result = await dataset_service.apply_tech_template(
                uow=mock_uow,
                dataset_id=db_dataset_rdbms.id,
                template_id=template.id,
            )
        assert len(result) == 1
        assert result[0].name == "valid_from"
        assert result[0].is_tech is True

    async def test_apply_tech_template_layer_mismatch(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms,
    ):
        from backend.models.tech_field_template import TechFieldTemplate

        db_dataset_rdbms.layer = "raw"
        template = TechFieldTemplate(
            id=uuid.uuid4(), code="scd2", name="SCD2", layer="core"
        )
        mock_uow.tech_field_templates = MagicMock()
        mock_uow.tech_field_templates.get = AsyncMock(return_value=template)
        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_dataset_rdbms

        with patch.object(dataset_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc:
                await dataset_service.apply_tech_template(
                    uow=mock_uow,
                    dataset_id=db_dataset_rdbms.id,
                    template_id=template.id,
                )
        assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_LAYER_MISMATCH

    async def test_apply_tech_template_unresolvable_type(
        self,
        dataset_service: DatasetService,
        mock_uow: _MockUnitOfWork,
        db_dataset_rdbms,
        db_system,
    ):
        from backend.models.system_flavor import SystemFlavor
        from backend.models.tech_field_template import (
            TechFieldTemplate,
            TechFieldTemplateField,
        )

        db_dataset_rdbms.layer = "core"
        template = TechFieldTemplate(
            id=uuid.uuid4(), code="scd2", name="SCD2", layer="core"
        )
        tpl_field = TechFieldTemplateField(
            id=uuid.uuid4(),
            template_id=template.id,
            name="foo",
            type_code="UNKNOWN",
            order=0,
        )
        flavor = SystemFlavor(
            id=uuid.uuid4(), code="postgres14", name="PG14", kind_id=uuid.uuid4()
        )

        mock_uow.tech_field_templates = MagicMock()
        mock_uow.tech_field_templates.get = AsyncMock(return_value=template)
        mock_uow.tech_field_template_fields = MagicMock()
        mock_uow.tech_field_template_fields.list_by_template = AsyncMock(
            return_value=[tpl_field]
        )
        mock_uow.system_flavors = MagicMock()
        mock_uow.system_flavors.get = AsyncMock(return_value=flavor)
        mock_uow.systems.get = AsyncMock(return_value=db_system)
        mock_uow.fields = MagicMock()
        mock_uow.fields.get_roots = AsyncMock(return_value=[])

        mock_repo = _MockRepository()
        mock_repo.get.return_value = db_dataset_rdbms
        fake_resolver = MagicMock()
        fake_resolver.resolve.return_value = None
        with (
            patch.object(dataset_service, "_get_repository", return_value=mock_repo),
            patch("backend.services.dataset.tech_type_resolver", new=fake_resolver),
        ):
            with pytest.raises(AppException) as exc:
                await dataset_service.apply_tech_template(
                    uow=mock_uow,
                    dataset_id=db_dataset_rdbms.id,
                    template_id=template.id,
                )
        assert exc.value.error_code == errors.TECH_TYPE_CODE_NOT_RESOLVABLE
