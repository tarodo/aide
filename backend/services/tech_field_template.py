import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.tech_field_template import TechFieldTemplate
from backend.repositories.tech_field_template import TechFieldTemplateRepository
from backend.schemas.tech_field_template import (
    TechFieldTemplateCreate,
    TechFieldTemplateRead,
    TechFieldTemplateUpdate,
)
from backend.services.base import GenericService


class TechFieldTemplateService(
    GenericService[
        TechFieldTemplate,
        TechFieldTemplateCreate,
        TechFieldTemplateUpdate,
        TechFieldTemplateRead,
    ]
):
    def __init__(self) -> None:
        super().__init__(
            model=TechFieldTemplate,
            repository=TechFieldTemplateRepository,
            read_schema=TechFieldTemplateRead,
            not_found_error_code=errors.TECH_FIELD_TEMPLATE_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: TechFieldTemplateCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(TechFieldTemplateRepository, self._get_repository(uow.session))
        if await repo.get_by_code(obj_in.code):
            raise AppException(errors.TECH_FIELD_TEMPLATE_ALREADY_EXISTS)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: TechFieldTemplate,
        obj_in: TechFieldTemplateUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        new_code = update_data.get("code")
        if new_code and new_code != db_obj.code:
            repo = cast(TechFieldTemplateRepository, self._get_repository(uow.session))
            existing = await repo.get_by_code(new_code)
            if existing and existing.id != db_obj.id:
                raise AppException(errors.TECH_FIELD_TEMPLATE_ALREADY_EXISTS)
