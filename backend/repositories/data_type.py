import uuid

from sqlalchemy import select

from backend.models.data_type import DataType
from backend.repositories.base import SoftDeleteRepository


class DataTypeRepository(SoftDeleteRepository[DataType]):
    model = DataType

    async def get_by_system_flavor_and_code(
        self, system_flavor_id: uuid.UUID, code: str
    ) -> DataType | None:
        """Get a non-deleted data type by system_flavor_id and code."""
        stmt = select(self.model).where(
            self.model.system_flavor_id == system_flavor_id,
            self.model.code == code,
            self.model.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
