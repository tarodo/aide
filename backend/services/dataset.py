import math
import uuid
from pathlib import Path
from typing import Any, cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.core.tech_type_resolver import TechTypeResolver
from backend.db.uow import UnitOfWork
from backend.schemas.field import FieldRead
from backend.schemas.pagination import Page
from backend.schemas.tech_field_template import TechFieldOverride
from backend.models.dataset import (
    Dataset,
    DatasetHive,
    DatasetKafka,
    DatasetRdbms,
    DatasetSftp,
    DatasetStorage,
)
from backend.repositories.dataset import DatasetRepository
from backend.schemas.dataset import (
    AnyDatasetCreate,
    AnyDatasetRead,
    AnyDatasetUpdate,
    validate_dataset_read,
)
from backend.services.base import SoftDeleteService

MODEL_MAP = {
    "rdbms": DatasetRdbms,
    "kafka": DatasetKafka,
    "storage": DatasetStorage,
    "sftp": DatasetSftp,
    "hive": DatasetHive,
}

_RESOLVER_YAML = (
    Path(__file__).resolve().parents[2]
    / "backend"
    / "scripts"
    / "data"
    / "tech_type_resolver.yaml"
)
tech_type_resolver = TechTypeResolver.from_yaml(_RESOLVER_YAML)


class DatasetService(
    SoftDeleteService[Dataset, AnyDatasetCreate, AnyDatasetUpdate, AnyDatasetRead]
):
    def __init__(self):
        super().__init__(
            model=Dataset,
            repository=DatasetRepository,
            read_schema=AnyDatasetRead,
            not_found_error_code=errors.DATASET_NOT_FOUND,
        )

    async def _pre_create(
        self, uow: UnitOfWork, obj_in: AnyDatasetCreate, creator_id: uuid.UUID | None
    ) -> None:
        repo = cast(DatasetRepository, self._get_repository(uow.session))
        if await repo.get_by_system_and_object_name(
            obj_in.system_id, obj_in.object_name
        ):
            raise AppException(errors.DATASET_ALREADY_EXISTS)
        if not await uow.systems.get(obj_in.system_id):
            raise AppException(errors.SYSTEM_NOT_FOUND)

    async def create(
        self,
        uow: UnitOfWork,
        obj_in: AnyDatasetCreate,
        creator_id: uuid.UUID | None = None,
    ) -> AnyDatasetRead:
        """Create a new dataset based on its kind."""
        obj_in_data = obj_in.model_dump()
        kind = obj_in_data.get("kind")
        if not isinstance(kind, str):
            raise AppException(errors.INVALID_DATASET_KIND)
        model_class = MODEL_MAP.get(kind)
        if not model_class:
            raise AppException(errors.INVALID_DATASET_KIND)

        async with uow:
            await self._pre_create(uow, obj_in, creator_id)
            repo = cast(DatasetRepository, self._get_repository(uow.session))
            db_obj = model_class(**obj_in_data)
            if creator_id:
                db_obj.created_by = creator_id
                db_obj.updated_by = creator_id

            created_obj = await repo.create(obj_in=db_obj)
            return validate_dataset_read(created_obj)

    async def get_by_id(self, uow: UnitOfWork, obj_id: uuid.UUID) -> AnyDatasetRead:
        """Get a dataset by its ID."""
        async with uow:
            repo = cast(DatasetRepository, self._get_repository(uow.session))
            db_obj = await repo.get(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)
            return validate_dataset_read(db_obj)

    async def get_paginated(
        self,
        uow: UnitOfWork,
        *,
        page: int,
        size: int,
        filters: dict[str, Any] | None = None,
        sort: list[tuple[str, bool]] | None = None,
        include_deleted: bool = False,
    ) -> Page[AnyDatasetRead]:
        """Get a paginated list of datasets."""
        skip = (page - 1) * size
        async with uow:
            repo = cast(DatasetRepository, self._get_repository(uow.session))
            items, total = await repo.get_multi_paginated(
                skip=skip,
                limit=size,
                filters=filters,
                sort=sort,
                include_deleted=include_deleted,
            )
            pages = math.ceil(total / size) if size > 0 else 0

            return Page[AnyDatasetRead](
                items=[validate_dataset_read(item) for item in items],
                total=total,
                page=page,
                size=size,
                pages=pages,
            )

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: Dataset,
        obj_in: AnyDatasetUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        if (
            "object_name" in update_data
            and update_data["object_name"] != db_obj.object_name
        ):
            repo = cast(DatasetRepository, self._get_repository(uow.session))
            if await repo.get_by_system_and_object_name(
                db_obj.system_id, update_data["object_name"]
            ):
                raise AppException(errors.DATASET_ALREADY_EXISTS)

    async def update(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        obj_in: AnyDatasetUpdate,
        updater_id: uuid.UUID | None = None,
    ) -> AnyDatasetRead:
        """Update an existing dataset."""
        update_data = obj_in.model_dump(exclude_unset=True)
        client_row_version = update_data.pop("row_version", None)

        async with uow:
            repo = cast(DatasetRepository, self._get_repository(uow.session))
            db_obj = await repo.get(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)

            if client_row_version is not None and hasattr(db_obj, "row_version"):
                if db_obj.row_version != client_row_version:
                    raise AppException(errors.VERSION_CONFLICT)

            if obj_in.kind != db_obj.kind:
                raise AppException(errors.DATASET_KIND_MISMATCH)

            await self._pre_update(uow, db_obj, obj_in, updater_id)

            update_data.pop("kind", None)
            for field, value in update_data.items():
                setattr(db_obj, field, value)

            if hasattr(db_obj, "row_version"):
                db_obj.row_version += 1

            if updater_id and hasattr(db_obj, "updated_by"):
                setattr(db_obj, "updated_by", updater_id)

            updated_obj = await repo.update(db_obj=db_obj)
            return validate_dataset_read(updated_obj)

    async def _pre_delete(self, uow: UnitOfWork, db_obj: Dataset) -> None:
        if await uow.dataset_links.has_active_links_for_dataset(db_obj.id):
            raise AppException(errors.DATASET_HAS_ACTIVE_LINKS)

    async def delete(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        deleter_id: uuid.UUID | None = None,
    ) -> AnyDatasetRead:
        """Soft-delete a dataset."""
        async with uow:
            repo = cast(DatasetRepository, self._get_repository(uow.session))
            db_obj = await repo.get(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)

            await self._pre_delete(uow, db_obj)

            if deleter_id and hasattr(db_obj, "deleted_by"):
                setattr(db_obj, "deleted_by", deleter_id)

            deleted_obj = await repo.delete(db_obj=db_obj)
            return validate_dataset_read(deleted_obj)

    async def restore(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        restorer_id: uuid.UUID | None = None,
    ) -> AnyDatasetRead:
        """Restore a soft-deleted dataset."""
        async with uow:
            repo = cast(DatasetRepository, self._get_repository(uow.session))
            db_obj = await repo.get_including_deleted(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)
            if not getattr(db_obj, "deleted_at", None):
                raise AppException(errors.ENTITY_NOT_DELETED)

            if restorer_id and hasattr(db_obj, "updated_by"):
                setattr(db_obj, "updated_by", restorer_id)

            restored_obj = await repo.restore(db_obj=db_obj)
            return validate_dataset_read(restored_obj)

    async def apply_tech_template(
        self,
        uow: UnitOfWork,
        dataset_id: uuid.UUID,
        template_id: uuid.UUID,
        overrides: list[TechFieldOverride] | None = None,
        applier_id: uuid.UUID | None = None,
    ) -> list[FieldRead]:
        """Apply a tech-field template to a dataset.

        Idempotent: existing field names on the dataset are skipped.

        Each new Field is created with ``origin="tech"`` and ``extra`` holding the
        resolved concrete data type as a pair of hints for downstream
        ``FieldBinding`` creation (Phase 3 work): ``extra["data_type_id"]`` is the
        stringified UUID of the resolved ``DataType`` row for the dataset's
        flavor; ``extra["tech_type_code"]`` is the abstract type_code applied
        (after any override). Consumers must cast ``data_type_id`` back to UUID.

        Validations bypass ``FieldService._pre_create`` on purpose: apply is a
        coarse-grained bulk operation, uniqueness is already enforced by the
        origin=="tech" skip + the root-name unique index, and per-field dataset
        existence checks are redundant here.
        """
        # Local import avoids a circular dependency: ``backend.models.field``
        # → ``backend.models.__init__`` → ``Dataset`` mappers.
        from backend.models.field import Field

        async with uow:
            repo = cast(DatasetRepository, self._get_repository(uow.session))
            dataset = await repo.get(dataset_id)
            if dataset is None:
                raise AppException(errors.DATASET_NOT_FOUND)

            template = await uow.tech_field_templates.get(template_id)
            if template is None:
                raise AppException(errors.TECH_FIELD_TEMPLATE_NOT_FOUND)

            if dataset.layer != template.layer:
                raise AppException(errors.TECH_FIELD_TEMPLATE_LAYER_MISMATCH)

            system = await uow.systems.get(dataset.system_id)
            if system is None:
                raise AppException(errors.SYSTEM_NOT_FOUND)
            flavor = await uow.system_flavors.get(system.flavor_id)
            if flavor is None:
                raise AppException(errors.SYSTEM_FLAVOR_NOT_FOUND)

            tpl_fields = await uow.tech_field_template_fields.list_by_template(
                template_id
            )
            override_map: dict[str, TechFieldOverride] = {
                o.name: o for o in (overrides or [])
            }
            existing_roots = await uow.fields.get_roots(dataset_id)
            existing_names = {f.name for f in existing_roots}

            new_fields: list[Field] = []
            for tf in tpl_fields:
                if tf.name in existing_names:
                    continue
                override = override_map.get(tf.name)
                type_code = (
                    override.type_code
                    if override and override.type_code
                    else tf.type_code
                )
                data_type_code = tech_type_resolver.resolve(flavor.code, type_code)
                if data_type_code is None:
                    raise AppException(errors.TECH_TYPE_CODE_NOT_RESOLVABLE)
                data_type = await uow.data_types.get_by_system_flavor_and_code(
                    flavor.id, data_type_code
                )
                if data_type is None:
                    raise AppException(errors.TECH_TYPE_CODE_NOT_RESOLVABLE)
                field = Field(
                    dataset_id=dataset_id,
                    name=tf.name,
                    origin="tech",
                    extra={
                        "data_type_id": str(data_type.id),
                        "tech_type_code": type_code,
                    },
                )
                if applier_id:
                    field.created_by = applier_id
                    field.updated_by = applier_id
                new_fields.append(field)

            if new_fields:
                await uow.fields.create_many(objs=new_fields)

            return [FieldRead.model_validate(f) for f in new_fields]
