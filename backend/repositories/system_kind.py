from sqlalchemy import select

from backend.models.system_kind import SystemKind
from backend.repositories.base import BaseRepository


class SystemKindRepository(BaseRepository[SystemKind]):
    model = SystemKind

    async def get_by_code(self, code: str) -> SystemKind | None:
        """Get a system kind by code."""
        stmt = select(self.model).where(self.model.code == code)
        result = await self.session.execute(stmt)
        return result.scalars().first()
