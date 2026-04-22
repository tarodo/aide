from sqlalchemy import select

from backend.models.tech_field_template import TechFieldTemplate
from backend.repositories.base import BaseRepository


class TechFieldTemplateRepository(BaseRepository[TechFieldTemplate]):
    model = TechFieldTemplate

    async def get_by_code(self, code: str) -> TechFieldTemplate | None:
        stmt = select(self.model).where(self.model.code == code)
        result = await self._execute(stmt, method="get_by_code")
        return result.scalars().first()
