import uuid
from typing import Any, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from backend.models.dataset import Dataset
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
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

    async def has_active_links_for_engine(self, engine_id: uuid.UUID) -> bool:
        from backend.models.dataset_link import DatasetLink as _DL

        stmt = (
            select(func.count())
            .select_from(_DL)
            .where(_DL.engine_id == engine_id, _DL.deleted_at.is_(None))
        )
        result = await self.session.execute(stmt)
        return (result.scalar_one() or 0) > 0

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

    async def list_with_compat_summary(self) -> list[dict[str, Any]]:
        """Return active DatasetLinks with pin drift metadata.

        Each row has: dataset_link_id, source/target dataset refs (id, object_name, system_id),
        pinned version, latest version (per side), has_drift flags.
        """
        src_latest = (
            select(
                DatasetSchema.dataset_id.label("ds_id"),
                func.max(DatasetSchema.version_num).label("max_v"),
            )
            .group_by(DatasetSchema.dataset_id)
            .subquery()
        )
        tgt_latest = aliased(src_latest)

        src_schema = aliased(DatasetSchema)
        tgt_schema = aliased(DatasetSchema)
        src_ds = aliased(Dataset)
        tgt_ds = aliased(Dataset)

        stmt = (
            select(
                self.model.id.label("dataset_link_id"),
                src_ds.id.label("source_dataset_id"),
                src_ds.object_name.label("source_object_name"),
                src_ds.system_id.label("source_system_id"),
                tgt_ds.id.label("target_dataset_id"),
                tgt_ds.object_name.label("target_object_name"),
                tgt_ds.system_id.label("target_system_id"),
                src_schema.version_num.label("source_pinned_version"),
                tgt_schema.version_num.label("target_pinned_version"),
                src_latest.c.max_v.label("source_latest_version"),
                tgt_latest.c.max_v.label("target_latest_version"),
            )
            .join(src_schema, src_schema.id == self.model.source_schema_id)
            .join(tgt_schema, tgt_schema.id == self.model.target_schema_id)
            .join(src_ds, src_ds.id == self.model.source_dataset_id)
            .join(tgt_ds, tgt_ds.id == self.model.target_dataset_id)
            .join(src_latest, src_latest.c.ds_id == self.model.source_dataset_id)
            .join(tgt_latest, tgt_latest.c.ds_id == self.model.target_dataset_id)
            .where(self.model.deleted_at.is_(None))
        )
        result = await self._execute(stmt, method="list_with_compat_summary")
        rows: list[dict[str, Any]] = []
        for row in result.mappings():
            d = dict(row)
            d["source_has_drift"] = (
                d["source_pinned_version"] != d["source_latest_version"]
            )
            d["target_has_drift"] = (
                d["target_pinned_version"] != d["target_latest_version"]
            )
            rows.append(d)
        return rows
