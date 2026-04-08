from sqlalchemy import select

from backend.models.system_flavor import SystemFlavor
from backend.repositories.base import SoftDeleteRepository


class SystemFlavorRepository(SoftDeleteRepository[SystemFlavor]):
    model = SystemFlavor

    async def get_by_code(self, code: str) -> SystemFlavor | None:
        """Get a non-deleted system flavor by code."""
        stmt = select(self.model).where(
            self.model.code == code,
            self.model.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
