import uuid
from typing import Any

from fastapi import APIRouter, Depends

from backend.api.dependencies import (
    get_current_user,
)
from backend.api.filter_sort import (
    FilterSortParams,
    get_filter_sort_dependency,
)
from backend.core.errors import (
    CRAWL_RUN_NOT_FOUND,
    SYSTEM_NOT_FOUND,
    UNAUTHORIZED,
    FORBIDDEN,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.crawl_run import (
    CrawlRunCreate,
    CrawlRunRead,
    CrawlRunUpdate,
)
from backend.schemas.filters import CRAWL_RUN_SORTABLE, CrawlRunFilter
from backend.schemas.pagination import Page
from backend.services.crawl_run import CrawlRunService

router = APIRouter()

_filter_sort_dep = get_filter_sort_dependency(
    CrawlRunFilter, CRAWL_RUN_SORTABLE, "started_at"
)


@router.get(
    "/",
    response_model=Page[CrawlRunRead],
    summary="Get all crawl runs (paginated)",
)
async def get_all(
    service: CrawlRunService = Depends(CrawlRunService),
    uow: UnitOfWork = Depends(UnitOfWork),
    params: FilterSortParams = Depends(_filter_sort_dep),
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
    response_model=CrawlRunRead,
    status_code=201,
    summary="Create a crawl run",
    responses={**build_error_responses(SYSTEM_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def create(
    obj_in: CrawlRunCreate,
    service: CrawlRunService = Depends(CrawlRunService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.get(
    "/{obj_id}",
    response_model=CrawlRunRead,
    summary="Get a crawl run by ID",
    responses={**build_error_responses(CRAWL_RUN_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)},
)
async def get_one(
    obj_id: uuid.UUID,
    service: CrawlRunService = Depends(CrawlRunService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    return await service.get_by_id(uow=uow, obj_id=obj_id)


@router.put(
    "/{obj_id}",
    response_model=CrawlRunRead,
    summary="Update a crawl run",
    responses={
        **build_error_responses(
            CRAWL_RUN_NOT_FOUND, VERSION_CONFLICT, UNAUTHORIZED, FORBIDDEN
        )
    },
)
async def update(
    obj_id: uuid.UUID,
    obj_in: CrawlRunUpdate,
    service: CrawlRunService = Depends(CrawlRunService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )
