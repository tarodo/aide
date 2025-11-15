import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.cast_rule import CastRule
from backend.repositories.cast_rule import CastRuleRepository
from backend.schemas.cast_rule import (
    CastRuleCreate,
    CastRuleRead,
    CastRuleUpdate,
)
from backend.services.base import GenericService


class CastRuleService(
    GenericService[CastRule, CastRuleCreate, CastRuleUpdate, CastRuleRead]
):
    """
    Service for cast rule related business logic.
    """

    def __init__(self):
        super().__init__(
            model=CastRule,
            repository=CastRuleRepository,
            read_schema=CastRuleRead,
            not_found_error_code=errors.CAST_RULE_NOT_FOUND,
        )

    async def _validate_data_types(
        self, uow: UnitOfWork, source_id: uuid.UUID, target_id: uuid.UUID
    ) -> None:
        if not await uow.data_types.get(source_id):
            raise AppException(errors.DATA_TYPE_NOT_FOUND)
        if not await uow.data_types.get(target_id):
            raise AppException(errors.DATA_TYPE_NOT_FOUND)

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: CastRuleCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(CastRuleRepository, self._get_repository(uow.session))
        if await repo.get_by_source_and_target_data_type_ids(
            obj_in.source_data_type_id, obj_in.target_data_type_id
        ):
            raise AppException(errors.CAST_RULE_ALREADY_EXISTS)
        await self._validate_data_types(
            uow, obj_in.source_data_type_id, obj_in.target_data_type_id
        )

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: CastRule,
        obj_in: CastRuleUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        repo = cast(CastRuleRepository, self._get_repository(uow.session))

        current_source_id = db_obj.source_data_type_id
        current_target_id = db_obj.target_data_type_id
        new_source_id = update_data.get("source_data_type_id", current_source_id)
        new_target_id = update_data.get("target_data_type_id", current_target_id)

        if new_source_id != current_source_id or new_target_id != current_target_id:
            if await repo.get_by_source_and_target_data_type_ids(
                new_source_id, new_target_id
            ):
                raise AppException(errors.CAST_RULE_ALREADY_EXISTS)

        if "source_data_type_id" in update_data or "target_data_type_id" in update_data:
            await self._validate_data_types(uow, new_source_id, new_target_id)
