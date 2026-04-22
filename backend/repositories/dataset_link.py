import uuid
from typing import Sequence

from sqlalchemy import or_, select

from backend.models.dataset_link import DatasetLink
from backend.repositories.base import SoftDeleteRepository


class DatasetLinkRepository(SoftDeleteRepository[DatasetLink]):
    model = DatasetLink

    async def get_active_between(
        self, source_dataset_id: uuid.UUID, target_dataset_id: uuid.UUID
    ) -> DatasetLink | None:
        stmt = select(self.model).where(
            self.model.source_dataset_id == source_dataset_id,
            self.model.target_dataset_id == target_dataset_id,
            self.model.deleted_at.is_(None),
        )
        result = await self._execute(stmt, method="get_active_between")
        return result.scalars().first()

    async def has_active_links_for_dataset(self, dataset_id: uuid.UUID) -> bool:
        stmt = (
            select(self.model.id)
            .where(
                or_(
                    self.model.source_dataset_id == dataset_id,
                    self.model.target_dataset_id == dataset_id,
                ),
                self.model.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self._execute(stmt, method="has_active_links_for_dataset")
        return result.scalar() is not None

    async def list_by_source(
        self, source_dataset_id: uuid.UUID
    ) -> Sequence[DatasetLink]:
        stmt = select(self.model).where(
            self.model.source_dataset_id == source_dataset_id,
            self.model.deleted_at.is_(None),
        )
        result = await self._execute(stmt, method="list_by_source")
        return result.scalars().all()

    async def list_by_target(
        self, target_dataset_id: uuid.UUID
    ) -> Sequence[DatasetLink]:
        stmt = select(self.model).where(
            self.model.target_dataset_id == target_dataset_id,
            self.model.deleted_at.is_(None),
        )
        result = await self._execute(stmt, method="list_by_target")
        return result.scalars().all()
