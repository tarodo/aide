from sqlalchemy import select

from backend.models.system_flavor import SystemFlavor
from backend.repositories.base import BaseRepository


class SystemFlavorRepository(BaseRepository[SystemFlavor]):
    model = SystemFlavor

    async def get_by_code(self, code: str) -> SystemFlavor | None:
        """Get a system flavor by code."""
        stmt = select(self.model).where(self.model.code == code)
        result = await self.session.execute(stmt)
        return result.scalars().first()
