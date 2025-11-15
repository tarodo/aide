import uuid

from sqlalchemy import select

from backend.models.cast_rule import CastRule
from backend.repositories.base import BaseRepository


class CastRuleRepository(BaseRepository[CastRule]):
    model = CastRule

    async def get_by_source_and_target_data_type_ids(
        self, source_data_type_id: uuid.UUID, target_data_type_id: uuid.UUID
    ) -> CastRule | None:
        """Get a cast rule by source and target data type IDs."""
        stmt = select(self.model).where(
            self.model.source_data_type_id == source_data_type_id,
            self.model.target_data_type_id == target_data_type_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
