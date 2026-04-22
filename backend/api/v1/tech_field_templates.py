import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_current_superuser, get_current_user
from backend.api.filter_sort import FilterSortParams, get_filter_sort_dependency
from backend.core.errors import (
    FORBIDDEN,
    TECH_FIELD_TEMPLATE_ALREADY_EXISTS,
    TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS,
    TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND,
    TECH_FIELD_TEMPLATE_NOT_FOUND,
    UNAUTHORIZED,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.filters import (
    TECH_FIELD_TEMPLATE_SORTABLE,
    TechFieldTemplateFilter,
)
from backend.schemas.pagination import Page
from backend.schemas.tech_field_template import (
    TechFieldTemplateCreate,
    TechFieldTemplateFieldCreate,
    TechFieldTemplateFieldRead,
    TechFieldTemplateFieldUpdate,
    TechFieldTemplateRead,
    TechFieldTemplateUpdate,
)
from backend.services.tech_field_template import TechFieldTemplateService
from backend.services.tech_field_template_field import TechFieldTemplateFieldService

router = APIRouter()

_filter_sort = get_filter_sort_dependency(
    TechFieldTemplateFilter, TECH_FIELD_TEMPLATE_SORTABLE, "code"
)


@router.get("/", response_model=Page[TechFieldTemplateRead])
async def list_templates(
    service: TechFieldTemplateService = Depends(TechFieldTemplateService),
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
    response_model=TechFieldTemplateRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            TECH_FIELD_TEMPLATE_ALREADY_EXISTS, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def create_template(
    obj_in: TechFieldTemplateCreate,
    service: TechFieldTemplateService = Depends(TechFieldTemplateService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.get(
    "/{obj_id}",
    response_model=TechFieldTemplateRead,
    responses={
        **build_error_responses(TECH_FIELD_TEMPLATE_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)
    },
)
async def get_template(
    obj_id: uuid.UUID,
    service: TechFieldTemplateService = Depends(TechFieldTemplateService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    return await service.get_by_id(uow=uow, obj_id=obj_id)


@router.patch(
    "/{obj_id}",
    response_model=TechFieldTemplateRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            TECH_FIELD_TEMPLATE_NOT_FOUND,
            TECH_FIELD_TEMPLATE_ALREADY_EXISTS,
            VERSION_CONFLICT,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def update_template(
    obj_id: uuid.UUID,
    obj_in: TechFieldTemplateUpdate,
    service: TechFieldTemplateService = Depends(TechFieldTemplateService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )


@router.delete(
    "/{obj_id}",
    response_model=TechFieldTemplateRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(TECH_FIELD_TEMPLATE_NOT_FOUND, UNAUTHORIZED, FORBIDDEN)
    },
)
async def delete_template(
    obj_id: uuid.UUID,
    service: TechFieldTemplateService = Depends(TechFieldTemplateService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)


@router.get(
    "/{template_id}/fields",
    response_model=list[TechFieldTemplateFieldRead],
)
async def list_template_fields(
    template_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    async with uow:
        items = await uow.tech_field_template_fields.list_by_template(template_id)
        return [TechFieldTemplateFieldRead.model_validate(i) for i in items]


@router.post(
    "/{template_id}/fields",
    response_model=TechFieldTemplateFieldRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            TECH_FIELD_TEMPLATE_NOT_FOUND,
            TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def create_template_field(
    template_id: uuid.UUID,
    obj_in: TechFieldTemplateFieldCreate,
    service: TechFieldTemplateFieldService = Depends(TechFieldTemplateFieldService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    obj_in = obj_in.model_copy(update={"template_id": template_id})
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.patch(
    "/fields/{obj_id}",
    response_model=TechFieldTemplateFieldRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND,
            VERSION_CONFLICT,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def update_template_field(
    obj_id: uuid.UUID,
    obj_in: TechFieldTemplateFieldUpdate,
    service: TechFieldTemplateFieldService = Depends(TechFieldTemplateFieldService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )


@router.delete(
    "/fields/{obj_id}",
    response_model=TechFieldTemplateFieldRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def delete_template_field(
    obj_id: uuid.UUID,
    service: TechFieldTemplateFieldService = Depends(TechFieldTemplateFieldService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)
