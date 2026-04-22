import uuid
from typing import Sequence

from sqlalchemy import select

from backend.models.tech_field_template import TechFieldTemplateField
from backend.repositories.base import BaseRepository


class TechFieldTemplateFieldRepository(BaseRepository[TechFieldTemplateField]):
    model = TechFieldTemplateField

    async def list_by_template(
        self, template_id: uuid.UUID
    ) -> Sequence[TechFieldTemplateField]:
        stmt = (
            select(self.model)
            .where(self.model.template_id == template_id)
            .order_by(self.model.order)
        )
        result = await self._execute(stmt, method="list_by_template")
        return result.scalars().all()

    async def get_by_template_and_name(
        self, template_id: uuid.UUID, name: str
    ) -> TechFieldTemplateField | None:
        stmt = select(self.model).where(
            self.model.template_id == template_id,
            self.model.name == name,
        )
        result = await self._execute(stmt, method="get_by_template_and_name")
        return result.scalars().first()
