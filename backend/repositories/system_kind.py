from sqlalchemy import select

from backend.models.system_kind import SystemKind
from backend.repositories.base import SoftDeleteRepository


class SystemKindRepository(SoftDeleteRepository[SystemKind]):
    model = SystemKind

    async def get_by_code(self, code: str) -> SystemKind | None:
        """Get a non-deleted system kind by code."""
        stmt = select(self.model).where(
            self.model.code == code,
            self.model.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
