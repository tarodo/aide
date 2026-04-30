import math
import uuid
from typing import Any, cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.engine import (
    Engine,
    EngineDebezium,
    EngineImpala,
    EngineOgg,
    EngineSpark,
)
from backend.repositories.engine import EngineRepository
from backend.schemas.engine import (
    AnyEngineCreate,
    AnyEngineRead,
    AnyEngineUpdate,
    validate_engine_read,
)
from backend.schemas.pagination import Page
from backend.services.base import SoftDeleteService

MODEL_MAP: dict[str, type[Engine]] = {
    "debezium": EngineDebezium,
    "ogg": EngineOgg,
    "spark": EngineSpark,
    "impala": EngineImpala,
}


class EngineService(
    SoftDeleteService[Engine, AnyEngineCreate, AnyEngineUpdate, AnyEngineRead]
):
    def __init__(self) -> None:
        super().__init__(
            model=Engine,
            repository=EngineRepository,
            read_schema=AnyEngineRead,  # type: ignore[arg-type]
            not_found_error_code=errors.ENGINE_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: AnyEngineCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(EngineRepository, self._get_repository(uow.session))
        if await repo.get_by_code(obj_in.code) is not None:
            raise AppException(errors.ENGINE_CODE_ALREADY_EXISTS)

    async def create(
        self,
        uow: UnitOfWork,
        obj_in: AnyEngineCreate,
        creator_id: uuid.UUID | None = None,
    ) -> AnyEngineRead:
        kind = obj_in.kind
        model_class = MODEL_MAP.get(kind)
        if model_class is None:
            raise AppException(errors.ENGINE_VERSION_INVALID)

        async with uow:
            await self._pre_create(uow, obj_in, creator_id)
            repo = cast(EngineRepository, self._get_repository(uow.session))
            data = obj_in.model_dump()
            data.pop("note", None)
            db_obj = model_class(**data)
            if creator_id:
                db_obj.created_by = creator_id
                db_obj.updated_by = creator_id
            created = await repo.create(obj_in=db_obj)
            return validate_engine_read(created)

    async def get_by_id(self, uow: UnitOfWork, obj_id: uuid.UUID) -> AnyEngineRead:
        async with uow:
            repo = cast(EngineRepository, self._get_repository(uow.session))
            db_obj = await repo.get(obj_id)
            if db_obj is None:
                raise AppException(self.not_found_error_code)
            return validate_engine_read(db_obj)

    async def get_paginated(
        self,
        uow: UnitOfWork,
        *,
        page: int,
        size: int,
        filters: dict[str, Any] | None = None,
        sort: list[tuple[str, bool]] | None = None,
        include_deleted: bool = False,
    ) -> Page[AnyEngineRead]:
        skip = (page - 1) * size
        async with uow:
            repo = cast(EngineRepository, self._get_repository(uow.session))
            items, total = await repo.get_multi_paginated(
                skip=skip,
                limit=size,
                filters=filters,
                sort=sort,
                include_deleted=include_deleted,
            )
            pages = math.ceil(total / size) if size > 0 else 0
            return Page[AnyEngineRead](
                items=[validate_engine_read(i) for i in items],
                total=total,
                page=page,
                size=size,
                pages=pages,
            )

    async def update(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        obj_in: AnyEngineUpdate,
        updater_id: uuid.UUID | None = None,
    ) -> AnyEngineRead:
        update_data = obj_in.model_dump(exclude_unset=True)
        client_row_version = update_data.pop("row_version", None)

        async with uow:
            repo = cast(EngineRepository, self._get_repository(uow.session))
            db_obj = await repo.get(obj_id)
            if db_obj is None:
                raise AppException(self.not_found_error_code)

            if obj_in.kind != db_obj.kind:
                raise AppException(errors.ENGINE_KIND_IMMUTABLE)

            if (
                client_row_version is not None
                and db_obj.row_version != client_row_version
            ):
                raise AppException(errors.VERSION_CONFLICT)

            update_data.pop("kind", None)
            for field, value in update_data.items():
                setattr(db_obj, field, value)

            db_obj.row_version += 1
            if updater_id:
                db_obj.updated_by = updater_id

            updated = await repo.update(db_obj=db_obj)
            return validate_engine_read(updated)

    async def _pre_delete(self, uow: UnitOfWork, db_obj: Engine) -> None:
        if await uow.dataset_links.has_active_links_for_engine(db_obj.id):
            raise AppException(errors.ENGINE_IN_USE)

    async def delete(
        self,
        uow: UnitOfWork,
        obj_id: uuid.UUID,
        deleter_id: uuid.UUID | None = None,
    ) -> AnyEngineRead:
        async with uow:
            repo = cast(EngineRepository, self._get_repository(uow.session))
            db_obj = await repo.get(obj_id)
            if db_obj is None:
                raise AppException(self.not_found_error_code)
            await self._pre_delete(uow, db_obj)
            if deleter_id:
                db_obj.deleted_by = deleter_id
            deleted = await repo.delete(db_obj=db_obj)
            return validate_engine_read(deleted)
