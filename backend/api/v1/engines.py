import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_current_superuser, get_current_user
from backend.api.filter_sort import FilterSortParams, get_filter_sort_dependency
from backend.core.errors import (
    ENGINE_CODE_ALREADY_EXISTS,
    ENGINE_IN_USE,
    ENGINE_KIND_IMMUTABLE,
    ENGINE_NOT_FOUND,
    ENGINE_VERSION_INVALID,
    ENTITY_NOT_DELETED,
    FORBIDDEN,
    UNAUTHORIZED,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.engine import AnyEngineCreate, AnyEngineRead, AnyEngineUpdate
from backend.schemas.filters import ENGINE_SORTABLE, EngineFilter
from backend.schemas.pagination import Page
from backend.services.engine import EngineService

router = APIRouter()

_filter_sort = get_filter_sort_dependency(EngineFilter, ENGINE_SORTABLE, "created_at")


@router.get("/", response_model=Page[AnyEngineRead])
async def list_engines(
    service: EngineService = Depends(EngineService),
    uow: UnitOfWork = Depends(UnitOfWork),
    params: FilterSortParams = Depends(_filter_sort),
) -> Any:
    return await service.get_paginated(
        uow=uow,
        page=params.page,
        size=params.size,
        filters=params.filters,
        sort=params.sort,
    )


@router.post(
    "/",
    response_model=AnyEngineRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            ENGINE_CODE_ALREADY_EXISTS,
            ENGINE_VERSION_INVALID,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def create_engine(
    obj_in: AnyEngineCreate,
    service: EngineService = Depends(EngineService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.get(
    "/{obj_id}",
    response_model=AnyEngineRead,
    responses={**build_error_responses(ENGINE_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def get_engine(
    obj_id: uuid.UUID,
    service: EngineService = Depends(EngineService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    return await service.get_by_id(uow=uow, obj_id=obj_id)


@router.patch(
    "/{obj_id}",
    response_model=AnyEngineRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            ENGINE_NOT_FOUND,
            ENGINE_KIND_IMMUTABLE,
            ENGINE_VERSION_INVALID,
            VERSION_CONFLICT,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def update_engine(
    obj_id: uuid.UUID,
    obj_in: AnyEngineUpdate,
    service: EngineService = Depends(EngineService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )


@router.delete(
    "/{obj_id}",
    response_model=AnyEngineRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            ENGINE_NOT_FOUND, ENGINE_IN_USE, UNAUTHORIZED, FORBIDDEN
        )
    },
)
async def delete_engine(
    obj_id: uuid.UUID,
    service: EngineService = Depends(EngineService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)


@router.post(
    "/{obj_id}/restore",
    response_model=AnyEngineRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            ENGINE_NOT_FOUND, ENTITY_NOT_DELETED, UNAUTHORIZED, FORBIDDEN
        )
    },
)
async def restore_engine(
    obj_id: uuid.UUID,
    service: EngineService = Depends(EngineService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.restore(uow=uow, obj_id=obj_id, restorer_id=current_user.id)
