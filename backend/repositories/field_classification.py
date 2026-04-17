import uuid
from typing import Sequence

from sqlalchemy import select

from backend.models.field import Field
from backend.models.field_classification import FieldClassification
from backend.repositories.base import BaseRepository


class FieldClassificationRepository(BaseRepository[FieldClassification]):
    model = FieldClassification

    async def get_current(self, field_id: uuid.UUID) -> FieldClassification | None:
        """Return the most recent classification for a field, or None."""
        stmt = (
            select(self.model)
            .where(self.model.field_id == field_id)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_field(self, field_id: uuid.UUID) -> Sequence[FieldClassification]:
        """Return all classifications for a field, newest first."""
        stmt = (
            select(self.model)
            .where(self.model.field_id == field_id)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_current_by_dataset(
        self, dataset_id: uuid.UUID
    ) -> Sequence[FieldClassification]:
        """For each field in the dataset with ≥1 classification, return the latest row."""
        latest_subq = (
            select(
                self.model.field_id,
                self.model.id.label("max_id"),
            )
            .join(Field, Field.id == self.model.field_id)
            .where(Field.dataset_id == dataset_id)
            .order_by(
                self.model.field_id,
                self.model.created_at.desc(),
                self.model.id.desc(),
            )
            .distinct(self.model.field_id)
            .subquery()
        )

        stmt = (
            select(self.model)
            .join(latest_subq, self.model.id == latest_subq.c.max_id)
            .order_by(self.model.field_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
