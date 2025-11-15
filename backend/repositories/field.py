import uuid

from sqlalchemy import select

from backend.models.field import Field
from backend.repositories.base import BaseRepository


class FieldRepository(BaseRepository[Field]):
    model = Field

    async def get_by_dataset_and_name(
        self, dataset_id: uuid.UUID, name: str
    ) -> Field | None:
        """Get a field by dataset_id and name."""
        stmt = select(self.model).where(
            self.model.dataset_id == dataset_id, self.model.name == name
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
