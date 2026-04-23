import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.field_link import FieldLink
from backend.repositories.field_link import FieldLinkRepository
from backend.schemas.field_link import (
    FieldLinkCreate,
    FieldLinkRead,
    FieldLinkUpdate,
)
from backend.services.base import GenericService


class FieldLinkService(
    GenericService[FieldLink, FieldLinkCreate, FieldLinkUpdate, FieldLinkRead]
):
    def __init__(self) -> None:
        super().__init__(
            model=FieldLink,
            repository=FieldLinkRepository,
            read_schema=FieldLinkRead,
            not_found_error_code=errors.FIELD_LINK_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: FieldLinkCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        link = await uow.dataset_links.get(obj_in.dataset_link_id)
        if link is None:
            raise AppException(errors.DATASET_LINK_NOT_FOUND)

        source_field = await uow.fields.get(obj_in.source_field_id)
        target_field = await uow.fields.get(obj_in.target_field_id)
        if source_field is None or target_field is None:
            raise AppException(errors.FIELD_NOT_FOUND)

        if source_field.dataset_id != link.source_dataset_id:
            raise AppException(errors.FIELD_LINK_SOURCE_DATASET_MISMATCH)
        if target_field.dataset_id != link.target_dataset_id:
            raise AppException(errors.FIELD_LINK_TARGET_DATASET_MISMATCH)

        # Target origin must be MAPPED — TECH/DEPRECATED targets don't accept
        # inbound FieldLinks (origin state machine lives on Field).
        if target_field.origin != "mapped":
            raise AppException(errors.FIELD_ORIGIN_CONFLICT)

        # Source and target must have FieldBindings in the parent link's
        # pinned schemas (schema-pinned lineage invariant).
        src_binding = await uow.field_bindings.get_by_field_and_schema(
            obj_in.source_field_id, link.source_schema_id
        )
        if src_binding is None:
            raise AppException(errors.FIELD_BINDING_MISSING)

        tgt_binding = await uow.field_bindings.get_by_field_and_schema(
            obj_in.target_field_id, link.target_schema_id
        )
        if tgt_binding is None:
            raise AppException(errors.FIELD_BINDING_MISSING)

        repo = cast(FieldLinkRepository, self._get_repository(uow.session))
        if await repo.get_by_target_in_link(link.id, target_field.id):
            raise AppException(errors.FIELD_LINK_TARGET_OCCUPIED)

    async def delete(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        deleter_id: uuid.UUID | None = None,
    ) -> FieldLinkRead:
        async with uow:
            repo = cast(FieldLinkRepository, self._get_repository(uow.session))
            db_obj = await repo.get(obj_id)
            if db_obj is None:
                raise AppException(errors.FIELD_LINK_NOT_FOUND)

            deleted = await repo.delete(db_obj=db_obj)
            return self.read_schema.model_validate(deleted)

    async def bulk_create(
        self,
        uow: UnitOfWork,
        items: list[FieldLinkCreate],
        creator_id: uuid.UUID | None = None,
    ) -> list[FieldLinkRead]:
        """Create many field_links in one transaction (all-or-nothing)."""
        if not items:
            return []
        async with uow:
            for it in items:
                await self._pre_create(uow, it, creator_id)
            repo = cast(FieldLinkRepository, self._get_repository(uow.session))
            db_objs: list[FieldLink] = []
            for it in items:
                obj = FieldLink(**it.model_dump())
                if creator_id:
                    obj.created_by = creator_id
                    obj.updated_by = creator_id
                db_objs.append(obj)
            created = await repo.create_many(objs=db_objs)
            return [self.read_schema.model_validate(o) for o in created]
