from sqlalchemy import select

from backend.models.system import System
from backend.repositories.base import SoftDeleteRepository


class SystemRepository(SoftDeleteRepository[System]):
    model = System

    async def get_by_code(self, code: str) -> System | None:
        """Get a non-deleted system by code."""
        stmt = select(self.model).where(
            self.model.code == code,
            self.model.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
