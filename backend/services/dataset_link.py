import uuid
from typing import cast

from aide_schemas.dataset import LAYER_ORDER, DatasetLayer

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.dataset_link import DatasetLink
from backend.repositories.dataset_link import DatasetLinkRepository
from backend.schemas.dataset_link import (
    DatasetLinkCreate,
    DatasetLinkRead,
    DatasetLinkUpdate,
)
from backend.services.base import SoftDeleteService


class DatasetLinkService(
    SoftDeleteService[
        DatasetLink, DatasetLinkCreate, DatasetLinkUpdate, DatasetLinkRead
    ]
):
    def __init__(self) -> None:
        super().__init__(
            model=DatasetLink,
            repository=DatasetLinkRepository,
            read_schema=DatasetLinkRead,
            not_found_error_code=errors.DATASET_LINK_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: DatasetLinkCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        if obj_in.source_dataset_id == obj_in.target_dataset_id:
            raise AppException(errors.DATASET_LINK_SELF_REFERENCE)

        source = await uow.datasets.get(obj_in.source_dataset_id)
        target = await uow.datasets.get(obj_in.target_dataset_id)
        if source is None or target is None:
            raise AppException(errors.DATASET_NOT_FOUND)

        if source.layer is None or target.layer is None:
            raise AppException(errors.DATASET_LINK_LAYER_MISSING)

        try:
            src_order = LAYER_ORDER[DatasetLayer(source.layer)]
            tgt_order = LAYER_ORDER[DatasetLayer(target.layer)]
        except (ValueError, KeyError) as exc:
            raise AppException(errors.DATASET_LINK_LAYER_MISSING) from exc

        if tgt_order <= src_order:
            raise AppException(errors.DATASET_LINK_LAYER_ORDER)

        repo = cast(DatasetLinkRepository, self._get_repository(uow.session))
        existing = await repo.get_active_between(
            obj_in.source_dataset_id, obj_in.target_dataset_id
        )
        if existing is not None:
            raise AppException(errors.DATASET_LINK_ALREADY_EXISTS)

        # Validate each pinned schema belongs to the corresponding dataset.
        src_schema = await uow.dataset_schemas.get(obj_in.source_schema_id)
        if src_schema is None:
            raise AppException(errors.DATASET_SCHEMA_NOT_FOUND)
        if src_schema.dataset_id != obj_in.source_dataset_id:
            raise AppException(errors.SCHEMA_DATASET_MISMATCH)

        tgt_schema = await uow.dataset_schemas.get(obj_in.target_schema_id)
        if tgt_schema is None:
            raise AppException(errors.DATASET_SCHEMA_NOT_FOUND)
        if tgt_schema.dataset_id != obj_in.target_dataset_id:
            raise AppException(errors.SCHEMA_DATASET_MISMATCH)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: DatasetLink,
        obj_in: DatasetLinkUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        new_src_schema_id = update_data.get("source_schema_id")
        if new_src_schema_id is not None:
            schema = await uow.dataset_schemas.get(new_src_schema_id)
            if schema is None:
                raise AppException(errors.DATASET_SCHEMA_NOT_FOUND)
            if schema.dataset_id != db_obj.source_dataset_id:
                raise AppException(errors.SCHEMA_DATASET_MISMATCH)
        new_tgt_schema_id = update_data.get("target_schema_id")
        if new_tgt_schema_id is not None:
            schema = await uow.dataset_schemas.get(new_tgt_schema_id)
            if schema is None:
                raise AppException(errors.DATASET_SCHEMA_NOT_FOUND)
            if schema.dataset_id != db_obj.target_dataset_id:
                raise AppException(errors.SCHEMA_DATASET_MISMATCH)

        if "engine_id" in update_data:
            new_engine_id = update_data["engine_id"]
            if new_engine_id is None:
                # detach is unconditionally allowed
                pass
            else:
                from backend.services.engine_compatibility import assert_compatible

                engine = await uow.engines.get(new_engine_id)
                if engine is None:
                    raise AppException(errors.ENGINE_NOT_FOUND)
                source = await uow.datasets.get(db_obj.source_dataset_id)
                target = await uow.datasets.get(db_obj.target_dataset_id)
                if source is None or target is None:
                    raise AppException(errors.DATASET_NOT_FOUND)
                assert_compatible(
                    role=engine.role,
                    source_kind=source.kind,
                    target_kind=target.kind,
                )
