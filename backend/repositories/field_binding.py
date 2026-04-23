import uuid

from sqlalchemy import select

from backend.models.field_binding import FieldBinding
from backend.repositories.base import BaseRepository


class FieldBindingRepository(BaseRepository[FieldBinding]):
    model = FieldBinding

    async def get_by_dataset_schema_and_field_id(
        self, dataset_schema_id: uuid.UUID, field_id: uuid.UUID
    ) -> FieldBinding | None:
        """Get a field binding by dataset_schema_id and field_id."""
        stmt = select(self.model).where(
            self.model.dataset_schema_id == dataset_schema_id,
            self.model.field_id == field_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_dataset_schema_and_position(
        self, dataset_schema_id: uuid.UUID, position: int
    ) -> FieldBinding | None:
        """Get a field binding by dataset_schema_id and position."""
        stmt = select(self.model).where(
            self.model.dataset_schema_id == dataset_schema_id,
            self.model.position == position,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_field_and_schema(
        self, field_id: uuid.UUID, dataset_schema_id: uuid.UUID
    ) -> FieldBinding | None:
        """Return the FieldBinding for (field, schema), or None."""
        stmt = select(FieldBinding).where(
            FieldBinding.field_id == field_id,
            FieldBinding.dataset_schema_id == dataset_schema_id,
        )
        result = await self._execute(stmt, method="get_by_field_and_schema")
        return result.scalars().first()
