import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.tech_field_template import TechFieldTemplateField
from backend.repositories.tech_field_template_field import (
    TechFieldTemplateFieldRepository,
)
from backend.schemas.tech_field_template import (
    TechFieldTemplateFieldCreate,
    TechFieldTemplateFieldRead,
    TechFieldTemplateFieldUpdate,
)
from backend.services.base import GenericService


class TechFieldTemplateFieldService(
    GenericService[
        TechFieldTemplateField,
        TechFieldTemplateFieldCreate,
        TechFieldTemplateFieldUpdate,
        TechFieldTemplateFieldRead,
    ]
):
    def __init__(self) -> None:
        super().__init__(
            model=TechFieldTemplateField,
            repository=TechFieldTemplateFieldRepository,
            read_schema=TechFieldTemplateFieldRead,
            not_found_error_code=errors.TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: TechFieldTemplateFieldCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        if not await uow.tech_field_templates.get(obj_in.template_id):
            raise AppException(errors.TECH_FIELD_TEMPLATE_NOT_FOUND)
        repo = cast(TechFieldTemplateFieldRepository, self._get_repository(uow.session))
        if await repo.get_by_template_and_name(obj_in.template_id, obj_in.name):
            raise AppException(errors.TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS)
