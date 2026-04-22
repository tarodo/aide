import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.dependencies import (
    get_current_superuser,
    get_current_user,
    get_current_user_optional,
)
from backend.api.filter_sort import FilterSortParams, get_filter_sort_dependency
from backend.core.errors import (
    DATASET_ALREADY_EXISTS,
    DATASET_KIND_MISMATCH,
    DATASET_NOT_FOUND,
    ENTITY_NOT_DELETED,
    FORBIDDEN,
    INVALID_DATASET_KIND,
    SYSTEM_FLAVOR_NOT_FOUND,
    SYSTEM_NOT_FOUND,
    TECH_FIELD_TEMPLATE_LAYER_MISMATCH,
    TECH_FIELD_TEMPLATE_NOT_FOUND,
    TECH_TYPE_CODE_NOT_RESOLVABLE,
    UNAUTHORIZED,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.dataset import AnyDatasetCreate, AnyDatasetRead, AnyDatasetUpdate
from backend.schemas.dataset_link import DatasetLinkRead
from backend.schemas.field import FieldRead
from backend.schemas.filters import DATASET_SORTABLE, DatasetFilter
from backend.schemas.pagination import Page
from backend.schemas.tech_field_template import ApplyTechTemplateRequest
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
    include_deleted: bool = Query(
        False, description="Include soft-deleted records (superuser only)"
    ),
    service: DatasetService = Depends(DatasetService),
    uow: UnitOfWork = Depends(UnitOfWork),
    params: FilterSortParams = Depends(_filter_sort),
    current_user: User | None = Depends(get_current_user_optional),
) -> Any:
    if include_deleted:
        if not current_user or not current_user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Superuser privileges required for include_deleted",
            )
    return await service.get_paginated(
        uow=uow,
        page=params.page,
        size=params.size,
        filters=params.filters,
        sort=params.sort,
        include_deleted=include_deleted,
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
            VERSION_CONFLICT,
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


@router.get(
    "/{obj_id}/upstream-links",
    response_model=list[DatasetLinkRead],
    summary="List dataset links where this dataset is the target",
    responses={**build_error_responses(DATASET_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def get_upstream_links(
    obj_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    async with uow:
        if not await uow.datasets.get(obj_id):
            raise AppException(DATASET_NOT_FOUND)
        items = await uow.dataset_links.list_by_target(obj_id)
        return [DatasetLinkRead.model_validate(i) for i in items]


@router.get(
    "/{obj_id}/downstream-links",
    response_model=list[DatasetLinkRead],
    summary="List dataset links where this dataset is the source",
    responses={**build_error_responses(DATASET_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def get_downstream_links(
    obj_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    async with uow:
        if not await uow.datasets.get(obj_id):
            raise AppException(DATASET_NOT_FOUND)
        items = await uow.dataset_links.list_by_source(obj_id)
        return [DatasetLinkRead.model_validate(i) for i in items]


@router.get(
    "/{obj_id}/unmapped-fields",
    response_model=list[FieldRead],
    summary="Non-technical fields of this dataset with no inbound field_link",
    responses={**build_error_responses(DATASET_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def get_unmapped_fields(
    obj_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    async with uow:
        if not await uow.datasets.get(obj_id):
            raise AppException(DATASET_NOT_FOUND)
        items = await uow.field_links.unmapped_non_tech_fields(obj_id)
        return [FieldRead.model_validate(i) for i in items]


@router.post(
    "/{obj_id}/apply-tech-template",
    response_model=list[FieldRead],
    status_code=status.HTTP_201_CREATED,
    summary="Apply a tech-field template to a dataset",
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_NOT_FOUND,
            TECH_FIELD_TEMPLATE_NOT_FOUND,
            TECH_FIELD_TEMPLATE_LAYER_MISMATCH,
            TECH_TYPE_CODE_NOT_RESOLVABLE,
            SYSTEM_NOT_FOUND,
            SYSTEM_FLAVOR_NOT_FOUND,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def apply_tech_template(
    obj_id: uuid.UUID,
    req: ApplyTechTemplateRequest,
    service: DatasetService = Depends(DatasetService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.apply_tech_template(
        uow=uow,
        dataset_id=obj_id,
        template_id=req.template_id,
        overrides=req.overrides,
        applier_id=current_user.id,
    )
