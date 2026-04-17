import uuid

from sqlalchemy import select

from backend.models.field_classification import FieldClassification
from backend.repositories.base import BaseRepository


class FieldClassificationRepository(BaseRepository[FieldClassification]):
    model = FieldClassification

    async def get_current(self, field_id: uuid.UUID) -> FieldClassification | None:
        """Return the most recent classification for a field, or None."""
        stmt = (
            select(self.model)
            .where(self.model.field_id == field_id)
            .order_by(self.model.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
