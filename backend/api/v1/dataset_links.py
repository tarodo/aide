import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_current_superuser, get_current_user
from backend.api.filter_sort import FilterSortParams, get_filter_sort_dependency
from backend.core.errors import (
    DATASET_LINK_ALREADY_EXISTS,
    DATASET_LINK_LAYER_MISSING,
    DATASET_LINK_LAYER_ORDER,
    DATASET_LINK_NOT_FOUND,
    DATASET_LINK_SELF_REFERENCE,
    DATASET_NOT_FOUND,
    DATASET_SCHEMA_NOT_FOUND,
    ENTITY_NOT_DELETED,
    FORBIDDEN,
    SCHEMA_DATASET_MISMATCH,
    UNAUTHORIZED,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.dataset_link import (
    DatasetLinkCreate,
    DatasetLinkRead,
    DatasetLinkUpdate,
)
from backend.schemas.filters import DATASET_LINK_SORTABLE, DatasetLinkFilter
from backend.schemas.pagination import Page
from backend.services.dataset_link import DatasetLinkService

router = APIRouter()

_filter_sort = get_filter_sort_dependency(
    DatasetLinkFilter, DATASET_LINK_SORTABLE, "created_at"
)


@router.get("/", response_model=Page[DatasetLinkRead])
async def list_links(
    service: DatasetLinkService = Depends(DatasetLinkService),
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
    response_model=DatasetLinkRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_NOT_FOUND,
            DATASET_SCHEMA_NOT_FOUND,
            DATASET_LINK_ALREADY_EXISTS,
            DATASET_LINK_SELF_REFERENCE,
            DATASET_LINK_LAYER_ORDER,
            DATASET_LINK_LAYER_MISSING,
            SCHEMA_DATASET_MISMATCH,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def create_link(
    obj_in: DatasetLinkCreate,
    service: DatasetLinkService = Depends(DatasetLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.get(
    "/{obj_id}",
    response_model=DatasetLinkRead,
    responses={
        **build_error_responses(DATASET_LINK_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)
    },
)
async def get_link(
    obj_id: uuid.UUID,
    service: DatasetLinkService = Depends(DatasetLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    return await service.get_by_id(uow=uow, obj_id=obj_id)


@router.patch(
    "/{obj_id}",
    response_model=DatasetLinkRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_LINK_NOT_FOUND,
            DATASET_SCHEMA_NOT_FOUND,
            SCHEMA_DATASET_MISMATCH,
            VERSION_CONFLICT,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def update_link(
    obj_id: uuid.UUID,
    obj_in: DatasetLinkUpdate,
    service: DatasetLinkService = Depends(DatasetLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )


@router.delete(
    "/{obj_id}",
    response_model=DatasetLinkRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(DATASET_LINK_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)
    },
)
async def delete_link(
    obj_id: uuid.UUID,
    service: DatasetLinkService = Depends(DatasetLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)


@router.post(
    "/{obj_id}/restore",
    response_model=DatasetLinkRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_LINK_NOT_FOUND, ENTITY_NOT_DELETED, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def restore_link(
    obj_id: uuid.UUID,
    service: DatasetLinkService = Depends(DatasetLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.restore(uow=uow, obj_id=obj_id, restorer_id=current_user.id)
