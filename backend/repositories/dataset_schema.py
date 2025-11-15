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
