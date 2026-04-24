import uuid

from sqlalchemy import select

from backend.models.dataset_schema import DatasetSchema
from backend.repositories.base import BaseRepository


class DatasetSchemaRepository(BaseRepository[DatasetSchema]):
    model = DatasetSchema

    async def get_by_dataset_id_and_version(
        self, dataset_id: uuid.UUID, version_num: int
    ) -> DatasetSchema | None:
        """Get a dataset schema by dataset_id and version_num."""
        stmt = select(self.model).where(
            self.model.dataset_id == dataset_id,
            self.model.version_num == version_num,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def latest_for_dataset(self, dataset_id: uuid.UUID) -> DatasetSchema | None:
        """Return the DatasetSchema with the highest version_num for a dataset,
        or None if the dataset has no schemas. Ties are impossible due to the
        unique constraint on (dataset_id, version_num)."""
        stmt = (
            select(DatasetSchema)
            .where(DatasetSchema.dataset_id == dataset_id)
            .order_by(DatasetSchema.version_num.desc())
            .limit(1)
        )
        result = await self._execute(stmt, method="latest_for_dataset")
        return result.scalars().first()
