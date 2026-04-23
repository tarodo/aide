import uuid
from typing import cast

from sqlalchemy import or_, select

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.dataset_link import DatasetLink
from backend.models.dataset_schema import DatasetSchema
from backend.repositories.base import BaseRepository
from backend.repositories.dataset_schema import DatasetSchemaRepository
from backend.schemas.dataset_schema import (
    DatasetSchemaCreate,
    DatasetSchemaRead,
    DatasetSchemaUpdate,
)
from backend.services.base import GenericService


class DatasetSchemaService(
    GenericService[
        DatasetSchema, DatasetSchemaCreate, DatasetSchemaUpdate, DatasetSchemaRead
    ]
):
    """
    Service for dataset schema related business logic.
    """

    def __init__(self):
        super().__init__(
            model=DatasetSchema,
            repository=DatasetSchemaRepository,
            read_schema=DatasetSchemaRead,
            not_found_error_code=errors.DATASET_SCHEMA_NOT_FOUND,
        )

    async def _validate_dependencies(
        self, uow: UnitOfWork, dataset_id: uuid.UUID
    ) -> None:
        if not await uow.datasets.get(dataset_id):
            raise AppException(errors.DATASET_NOT_FOUND)

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: DatasetSchemaCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(DatasetSchemaRepository, self._get_repository(uow.session))
        if await repo.get_by_dataset_id_and_version(
            obj_in.dataset_id, obj_in.version_num
        ):
            raise AppException(errors.DATASET_SCHEMA_ALREADY_EXISTS)
        await self._validate_dependencies(uow, obj_in.dataset_id)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: DatasetSchema,
        obj_in: DatasetSchemaUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        repo = cast(DatasetSchemaRepository, self._get_repository(uow.session))

        current_dataset_id = db_obj.dataset_id
        current_version = db_obj.version_num
        new_dataset_id = update_data.get("dataset_id", current_dataset_id)
        new_version = update_data.get("version_num", current_version)

        if new_dataset_id != current_dataset_id or new_version != current_version:
            if await repo.get_by_dataset_id_and_version(new_dataset_id, new_version):
                raise AppException(errors.DATASET_SCHEMA_ALREADY_EXISTS)

        if "dataset_id" in update_data:
            await self._validate_dependencies(uow, new_dataset_id)

    async def create(
        self,
        uow: UnitOfWork,
        obj_in: DatasetSchemaCreate,
        creator_id: uuid.UUID | None = None,
    ) -> DatasetSchemaRead:
        """Create a new object."""
        obj_in_data = obj_in.model_dump()
        if "schema_" in obj_in_data:
            obj_in_data["schema"] = obj_in_data.pop("schema_")

        async with uow:
            await self._pre_create(uow, obj_in, creator_id)
            repo: BaseRepository[DatasetSchema] = self._get_repository(uow.session)
            db_obj = self.model(**obj_in_data)
            if creator_id and hasattr(db_obj, "created_by"):
                setattr(db_obj, "created_by", creator_id)
                setattr(db_obj, "updated_by", creator_id)

            created_obj = await repo.create(obj_in=db_obj)
            return self.read_schema.model_validate(created_obj)

    async def update(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        obj_in: DatasetSchemaUpdate,
        updater_id: uuid.UUID | None = None,
    ) -> DatasetSchemaRead:
        """Update an existing object."""
        update_data = obj_in.model_dump(exclude_unset=True)
        if "schema_" in update_data:
            update_data["schema"] = update_data.pop("schema_")

        return await super().update(uow, obj_id, obj_in, updater_id)

    async def _pre_delete(
        self,
        uow: UnitOfWork,
        db_obj: DatasetSchema,
        deleter_id: uuid.UUID | None,
    ) -> None:
        """Block deletion when the schema is pinned by an active DatasetLink.

        The DB FK uses ON DELETE RESTRICT, which would raise an IntegrityError
        at commit time. Catching this at the service layer yields a clean
        AppException(DATASET_SCHEMA_IN_USE) → HTTP 409.
        """
        stmt = (
            select(DatasetLink.id)
            .where(
                or_(
                    DatasetLink.source_schema_id == db_obj.id,
                    DatasetLink.target_schema_id == db_obj.id,
                ),
                DatasetLink.deleted_at.is_(None),
            )
            .limit(5)
        )
        result = await uow.session.execute(stmt)
        blocking = [row[0] for row in result.all()]
        if blocking:
            raise AppException(errors.DATASET_SCHEMA_IN_USE)

    async def delete(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        deleter_id: uuid.UUID | None = None,
    ) -> DatasetSchemaRead:
        """Hard-delete a dataset schema after checking for active DatasetLink pins."""
        async with uow:
            repo: BaseRepository[DatasetSchema] = self._get_repository(uow.session)
            db_obj = await repo.get(obj_id)
            if not db_obj:
                raise AppException(self.not_found_error_code)

            await self._pre_delete(uow, db_obj, deleter_id)

            deleted_obj = await repo.delete(db_obj=db_obj)
            return self.read_schema.model_validate(deleted_obj)
