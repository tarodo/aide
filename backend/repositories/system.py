from sqlalchemy import select

from backend.models.system import System
from backend.repositories.base import BaseRepository


class SystemRepository(BaseRepository[System]):
    model = System

    async def get_by_code(self, code: str) -> System | None:
        """Get a system by code."""
        stmt = select(self.model).where(self.model.code == code)
        result = await self.session.execute(stmt)
        return result.scalars().first()
