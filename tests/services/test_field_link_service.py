import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.dataset_link import DatasetLink
from backend.models.field import Field
from backend.models.field_binding import FieldBinding
from backend.models.field_link import FieldLink
from backend.schemas.field_link import FieldLinkCreate, FieldLinkRead
from backend.services.field_link import FieldLinkService


class _MockRepo:
    def __init__(self) -> None:
        self.get = AsyncMock()
        self.get_by_target_in_link = AsyncMock(return_value=None)
        self.count_by_target_field = AsyncMock(return_value=0)
        self.list_by_dataset_link = AsyncMock(return_value=[])
        self.list_by_target_field = AsyncMock(return_value=[])
        self.unmapped_non_tech_fields = AsyncMock(return_value=[])
        self.create = AsyncMock()
        self.update = AsyncMock()
        self.delete = AsyncMock()
        self.get_multi_paginated = AsyncMock(return_value=([], 0))


class _MockUoW:
    def __init__(self) -> None:
        self.session = AsyncMock()
        self.dataset_links = AsyncMock()
        self.fields = AsyncMock()
        self.field_bindings = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _field(dataset_id: uuid.UUID, origin: str = "mapped") -> Field:
    return Field(
        id=uuid.uuid4(),
        dataset_id=dataset_id,
        name="c",
        origin=origin,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        row_version=1,
    )


def _link(
    src: uuid.UUID,
    tgt: uuid.UUID,
    src_schema: uuid.UUID | None = None,
    tgt_schema: uuid.UUID | None = None,
) -> DatasetLink:
    return DatasetLink(
        id=uuid.uuid4(),
        source_dataset_id=src,
        target_dataset_id=tgt,
        source_schema_id=src_schema or uuid.uuid4(),
        target_schema_id=tgt_schema or uuid.uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        row_version=1,
    )


def _binding(field_id: uuid.UUID, schema_id: uuid.UUID) -> FieldBinding:
    return FieldBinding(
        id=uuid.uuid4(),
        field_id=field_id,
        dataset_schema_id=schema_id,
        position=0,
        is_nullable=True,
        type_instance_id=uuid.uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        row_version=1,
    )


@pytest.fixture
def service() -> FieldLinkService:
    return FieldLinkService()


@pytest.mark.asyncio
class TestFieldLinkService:
    async def test_create_happy(self, service: FieldLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf, tf = _field(src_id), _field(tgt_id)
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        uow.field_bindings.get_by_field_and_schema.side_effect = [
            _binding(sf.id, link.source_schema_id),
            _binding(tf.id, link.target_schema_id),
        ]
        repo = _MockRepo()
        repo.create.return_value = FieldLink(
            id=uuid.uuid4(),
            dataset_link_id=link.id,
            source_field_id=sf.id,
            target_field_id=tf.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=FieldLinkCreate(
                    dataset_link_id=link.id,
                    source_field_id=sf.id,
                    target_field_id=tf.id,
                ),
            )
        assert isinstance(result, FieldLinkRead)

    async def test_create_rejects_wrong_source_dataset(self, service: FieldLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf = _field(uuid.uuid4())  # wrong dataset
        tf = _field(tgt_id)
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=FieldLinkCreate(
                        dataset_link_id=link.id,
                        source_field_id=sf.id,
                        target_field_id=tf.id,
                    ),
                )
        assert exc.value.error_code == errors.FIELD_LINK_SOURCE_DATASET_MISMATCH

    async def test_create_rejects_wrong_target_dataset(self, service: FieldLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf = _field(src_id)
        tf = _field(uuid.uuid4())  # wrong dataset
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=FieldLinkCreate(
                        dataset_link_id=link.id,
                        source_field_id=sf.id,
                        target_field_id=tf.id,
                    ),
                )
        assert exc.value.error_code == errors.FIELD_LINK_TARGET_DATASET_MISMATCH

    async def test_create_rejects_when_target_origin_not_mapped(
        self, service: FieldLinkService
    ):
        """target_field.origin='deprecated' -> FIELD_ORIGIN_CONFLICT."""
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf = _field(src_id)
        tf = _field(tgt_id, origin="deprecated")
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=FieldLinkCreate(
                        dataset_link_id=link.id,
                        source_field_id=sf.id,
                        target_field_id=tf.id,
                    ),
                )
        assert exc.value.error_code == errors.FIELD_ORIGIN_CONFLICT
        repo.create.assert_not_awaited()

    async def test_create_rejects_when_target_origin_tech(
        self, service: FieldLinkService
    ):
        """target_field.origin='tech' -> FIELD_ORIGIN_CONFLICT."""
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf = _field(src_id)
        tf = _field(tgt_id, origin="tech")
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=FieldLinkCreate(
                        dataset_link_id=link.id,
                        source_field_id=sf.id,
                        target_field_id=tf.id,
                    ),
                )
        assert exc.value.error_code == errors.FIELD_ORIGIN_CONFLICT

    async def test_create_rejects_when_source_has_no_binding_in_pinned_schema(
        self, service: FieldLinkService
    ):
        """field_bindings.get_by_field_and_schema returns None for source."""
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf, tf = _field(src_id), _field(tgt_id)
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        uow.field_bindings.get_by_field_and_schema.side_effect = [
            None,  # no binding for source
            _binding(tf.id, link.target_schema_id),
        ]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=FieldLinkCreate(
                        dataset_link_id=link.id,
                        source_field_id=sf.id,
                        target_field_id=tf.id,
                    ),
                )
        assert exc.value.error_code == errors.FIELD_BINDING_MISSING
        repo.create.assert_not_awaited()

    async def test_create_rejects_when_target_has_no_binding_in_pinned_schema(
        self, service: FieldLinkService
    ):
        """field_bindings.get_by_field_and_schema returns None for target."""
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf, tf = _field(src_id), _field(tgt_id)
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        uow.field_bindings.get_by_field_and_schema.side_effect = [
            _binding(sf.id, link.source_schema_id),
            None,  # no binding for target
        ]
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=FieldLinkCreate(
                        dataset_link_id=link.id,
                        source_field_id=sf.id,
                        target_field_id=tf.id,
                    ),
                )
        assert exc.value.error_code == errors.FIELD_BINDING_MISSING
        repo.create.assert_not_awaited()

    async def test_create_passes_when_bindings_exist_and_target_mapped(
        self, service: FieldLinkService
    ):
        """All checks pass -> no exception."""
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf, tf = _field(src_id, origin="mapped"), _field(tgt_id, origin="mapped")
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        uow.field_bindings.get_by_field_and_schema.side_effect = [
            _binding(sf.id, link.source_schema_id),
            _binding(tf.id, link.target_schema_id),
        ]
        repo = _MockRepo()
        repo.create.return_value = FieldLink(
            id=uuid.uuid4(),
            dataset_link_id=link.id,
            source_field_id=sf.id,
            target_field_id=tf.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=FieldLinkCreate(
                    dataset_link_id=link.id,
                    source_field_id=sf.id,
                    target_field_id=tf.id,
                ),
            )
        assert isinstance(result, FieldLinkRead)
        repo.create.assert_awaited_once()

    async def test_create_rejects_target_occupied(self, service: FieldLinkService):
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        link = _link(src_id, tgt_id)
        sf, tf = _field(src_id), _field(tgt_id)
        uow = _MockUoW()
        uow.dataset_links.get.return_value = link
        uow.fields.get.side_effect = [sf, tf]
        uow.field_bindings.get_by_field_and_schema.side_effect = [
            _binding(sf.id, link.source_schema_id),
            _binding(tf.id, link.target_schema_id),
        ]
        repo = _MockRepo()
        repo.get_by_target_in_link.return_value = FieldLink(id=uuid.uuid4())
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=FieldLinkCreate(
                        dataset_link_id=link.id,
                        source_field_id=sf.id,
                        target_field_id=tf.id,
                    ),
                )
        assert exc.value.error_code == errors.FIELD_LINK_TARGET_OCCUPIED

    async def test_delete_ok(self, service: FieldLinkService):
        """Delete no longer enforces 'non-tech requires source' -- always ok."""
        tgt_id = uuid.uuid4()
        tf = _field(tgt_id)
        fl = FieldLink(
            id=uuid.uuid4(),
            dataset_link_id=uuid.uuid4(),
            source_field_id=uuid.uuid4(),
            target_field_id=tf.id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        uow = _MockUoW()
        uow.fields.get.return_value = tf
        repo = _MockRepo()
        repo.get.return_value = fl
        repo.delete.return_value = fl
        with patch.object(service, "_get_repository", return_value=repo):
            await service.delete(uow=uow, obj_id=fl.id)
        repo.delete.assert_awaited_once()
