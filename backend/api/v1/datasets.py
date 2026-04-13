import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import (
    get_current_superuser,
    get_current_user,
)
from backend.api.filter_sort import FilterSortParams, get_filter_sort_dependency
from backend.core.errors import (
    DATASET_ALREADY_EXISTS,
    DATASET_KIND_MISMATCH,
    DATASET_NOT_FOUND,
    ENTITY_NOT_DELETED,
    FORBIDDEN,
    INVALID_DATASET_KIND,
    SYSTEM_NOT_FOUND,
    UNAUTHORIZED,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.dataset import AnyDatasetCreate, AnyDatasetRead, AnyDatasetUpdate
from backend.schemas.filters import DATASET_SORTABLE, DatasetFilter
from backend.schemas.pagination import Page
from backend.services.dataset import DatasetService

router = APIRouter()

_filter_sort = get_filter_sort_dependency(
    DatasetFilter, DATASET_SORTABLE, "object_name"
)


@router.get(
    "/",
    response_model=Page[AnyDatasetRead],
    summary="Get all datasets (paginated)",
)
async def get_all(
    service: DatasetService = Depends(DatasetService),
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
    response_model=AnyDatasetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new dataset (admin only)",
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_ALREADY_EXISTS,
            SYSTEM_NOT_FOUND,
            INVALID_DATASET_KIND,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def create(
    obj_in: AnyDatasetCreate,
    service: DatasetService = Depends(DatasetService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    creator_id = current_user.id
    return await service.create(uow=uow, obj_in=obj_in, creator_id=creator_id)


@router.get(
    "/{obj_id}",
    response_model=AnyDatasetRead,
    summary="Get a dataset by ID",
    responses={
        **build_error_responses(DATASET_NOT_FOUND, UNAUTHORIZED, FORBIDDEN),
    },
)
async def get_one(
    obj_id: uuid.UUID,
    service: DatasetService = Depends(DatasetService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    return await service.get_by_id(uow=uow, obj_id=obj_id)


@router.patch(
    "/{obj_id}",
    response_model=AnyDatasetRead,
    summary="Update a dataset",
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_NOT_FOUND,
            DATASET_ALREADY_EXISTS,
            DATASET_KIND_MISMATCH,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def update(
    obj_id: uuid.UUID,
    obj_in: AnyDatasetUpdate,
    service: DatasetService = Depends(DatasetService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    updater_id = current_user.id
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=updater_id
    )


@router.delete(
    "/{obj_id}",
    response_model=AnyDatasetRead,
    summary="Delete a dataset",
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(DATASET_NOT_FOUND, UNAUTHORIZED, FORBIDDEN),
    },
)
async def delete(
    obj_id: uuid.UUID,
    service: DatasetService = Depends(DatasetService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)


@router.post(
    "/{obj_id}/restore",
    response_model=AnyDatasetRead,
    summary="Restore a deleted dataset",
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_NOT_FOUND, ENTITY_NOT_DELETED, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def restore(
    obj_id: uuid.UUID,
    service: DatasetService = Depends(DatasetService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.restore(uow=uow, obj_id=obj_id, restorer_id=current_user.id)
