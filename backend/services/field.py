import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.field import Field
from backend.repositories.field import FieldRepository
from backend.schemas.field import (
    FieldCreate,
    FieldRead,
    FieldTree,
    FieldUpdate,
)
from backend.services.base import GenericService


class FieldService(GenericService[Field, FieldCreate, FieldUpdate, FieldRead]):
    """
    Service for field related business logic.
    """

    def __init__(self):
        super().__init__(
            model=Field,
            repository=FieldRepository,
            read_schema=FieldRead,
            not_found_error_code=errors.FIELD_NOT_FOUND,
        )

    async def _validate_dependencies(
        self, uow: UnitOfWork, dataset_id: uuid.UUID
    ) -> None:
        if not await uow.datasets.get(dataset_id):
            raise AppException(errors.DATASET_NOT_FOUND)

    async def _validate_parent(
        self, uow: UnitOfWork, parent_id: uuid.UUID, dataset_id: uuid.UUID
    ) -> None:
        """Validate that parent exists and belongs to the same dataset."""
        parent = await uow.fields.get(parent_id)
        if not parent:
            raise AppException(errors.FIELD_PARENT_NOT_FOUND)
        if parent.dataset_id != dataset_id:
            raise AppException(errors.FIELD_PARENT_DATASET_MISMATCH)

    async def _check_circular_reference(
        self, uow: UnitOfWork, field_id: uuid.UUID, new_parent_id: uuid.UUID
    ) -> None:
        """Walk up the ancestor chain from new_parent_id to ensure field_id is not encountered."""
        current_id: uuid.UUID | None = new_parent_id
        visited = set()
        while current_id is not None:
            if current_id == field_id:
                raise AppException(errors.FIELD_CIRCULAR_REFERENCE)
            if current_id in visited:
                break
            visited.add(current_id)
            parent = await uow.fields.get(current_id)
            if not parent:
                break
            current_id = parent.parent_id

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: FieldCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        await self._validate_dependencies(uow, obj_in.dataset_id)

        if obj_in.parent_id is not None:
            await self._validate_parent(uow, obj_in.parent_id, obj_in.dataset_id)

        repo = cast(FieldRepository, self._get_repository(uow.session))
        if await repo.get_by_dataset_and_name(
            obj_in.dataset_id, obj_in.name, obj_in.parent_id
        ):
            raise AppException(errors.FIELD_ALREADY_EXISTS)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: Field,
        obj_in: FieldUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        repo = cast(FieldRepository, self._get_repository(uow.session))

        current_dataset_id = db_obj.dataset_id
        current_name = db_obj.name
        current_parent_id = db_obj.parent_id
        new_dataset_id = update_data.get("dataset_id", current_dataset_id)
        new_name = update_data.get("name", current_name)
        new_parent_id = update_data.get("parent_id", current_parent_id)

        if "dataset_id" in update_data:
            await self._validate_dependencies(uow, new_dataset_id)

        if "parent_id" in update_data and new_parent_id is not None:
            await self._validate_parent(uow, new_parent_id, new_dataset_id)
            await self._check_circular_reference(uow, db_obj.id, new_parent_id)

        if (
            new_dataset_id != current_dataset_id
            or new_name != current_name
            or new_parent_id != current_parent_id
        ):
            existing = await repo.get_by_dataset_and_name(
                new_dataset_id, new_name, new_parent_id
            )
            if existing and existing.id != db_obj.id:
                raise AppException(errors.FIELD_ALREADY_EXISTS)

    async def get_tree(self, uow: UnitOfWork, dataset_id: uuid.UUID) -> list[FieldTree]:
        """Return the full field tree for a dataset."""
        async with uow:
            await self._validate_dependencies(uow, dataset_id)
            repo = cast(FieldRepository, uow.fields)
            roots = await repo.get_tree(dataset_id)
            return [FieldTree.model_validate(root) for root in roots]

    async def get_children(
        self, uow: UnitOfWork, field_id: uuid.UUID
    ) -> list[FieldRead]:
        """Return direct children of a field."""
        async with uow:
            db_obj = await uow.fields.get(field_id)
            if not db_obj:
                raise AppException(errors.FIELD_NOT_FOUND)
            repo = cast(FieldRepository, uow.fields)
            children = await repo.get_children(field_id)
            return [FieldRead.model_validate(child) for child in children]
