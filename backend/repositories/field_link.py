import uuid
from typing import Sequence

from sqlalchemy import func, select

from backend.models.field import Field
from backend.models.field_link import FieldLink
from backend.repositories.base import BaseRepository


class FieldLinkRepository(BaseRepository[FieldLink]):
    model = FieldLink

    async def list_by_dataset_link(
        self, dataset_link_id: uuid.UUID
    ) -> Sequence[FieldLink]:
        stmt = select(self.model).where(self.model.dataset_link_id == dataset_link_id)
        result = await self._execute(stmt, method="list_by_dataset_link")
        return result.scalars().all()

    async def get_by_target_in_link(
        self, dataset_link_id: uuid.UUID, target_field_id: uuid.UUID
    ) -> FieldLink | None:
        stmt = select(self.model).where(
            self.model.dataset_link_id == dataset_link_id,
            self.model.target_field_id == target_field_id,
        )
        result = await self._execute(stmt, method="get_by_target_in_link")
        return result.scalars().first()

    async def list_by_target_field(
        self, target_field_id: uuid.UUID
    ) -> Sequence[FieldLink]:
        stmt = select(self.model).where(self.model.target_field_id == target_field_id)
        result = await self._execute(stmt, method="list_by_target_field")
        return result.scalars().all()

    async def count_by_target_field(self, target_field_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.target_field_id == target_field_id)
        )
        result = await self._execute(stmt, method="count_by_target_field")
        return int(result.scalar_one())

    async def unmapped_non_tech_fields(
        self, target_dataset_id: uuid.UUID
    ) -> Sequence[Field]:
        """Fields in the given dataset with origin='mapped' and no inbound FieldLink."""
        has_link = (
            select(self.model.id).where(self.model.target_field_id == Field.id).exists()
        )
        stmt = select(Field).where(
            Field.dataset_id == target_dataset_id,
            Field.origin == "mapped",
            ~has_link,
        )
        result = await self._execute(stmt, method="unmapped_non_tech_fields")
        return result.scalars().all()
