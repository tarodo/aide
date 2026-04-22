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
        except (ValueError, KeyError):
            raise AppException(errors.DATASET_LINK_LAYER_MISSING)

        if tgt_order <= src_order:
            raise AppException(errors.DATASET_LINK_LAYER_ORDER)

        repo = cast(DatasetLinkRepository, self._get_repository(uow.session))
        existing = await repo.get_active_between(
            obj_in.source_dataset_id, obj_in.target_dataset_id
        )
        if existing is not None:
            raise AppException(errors.DATASET_LINK_ALREADY_EXISTS)
