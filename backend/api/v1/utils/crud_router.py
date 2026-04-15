import uuid
from typing import Any, List, Sequence, Type, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from backend.core.settings import settings
from backend.schemas.batch import BatchCreateRequest, BatchCreateResponse

from backend.api.dependencies import (
    PaginationParams,
    get_current_superuser,
    get_current_user,
    get_current_user_optional,
    get_pagination_params,
)
from backend.api.filter_sort import (
    BaseFilter,
    FilterSortParams,
    get_filter_sort_dependency,
)
from backend.core.errors import FORBIDDEN, UNAUTHORIZED, build_error_responses
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.pagination import Page
from backend.services.base import GenericService

CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)
ReadSchemaType = TypeVar("ReadSchemaType", bound=BaseModel)
ServiceType = TypeVar("ServiceType", bound=GenericService[Any, Any, Any, Any])


def create_crud_router(
    *,
    service_dependency: Type[ServiceType],
    create_schema: Type[CreateSchemaType],
    update_schema: Type[UpdateSchemaType],
    read_schema: Type[ReadSchemaType],
    entity_name: str,
    get_all_dependencies: Sequence[Any] | None = None,
    create_dependencies: Sequence[Any] | None = None,
    get_one_dependencies: Sequence[Any] | None = None,
    update_dependencies: Sequence[Any] | None = None,
    delete_dependencies: Sequence[Any] | None = None,
    create_error_codes: List[str] | None = None,
    update_error_codes: List[str] | None = None,
    get_one_error_codes: List[str] | None = None,
    delete_error_codes: List[str] | None = None,
    supports_restore: bool = False,
    restore_dependencies: Sequence[Any] | None = None,
    restore_error_codes: List[str] | None = None,
    filter_model: Type[BaseFilter] | None = None,
    sortable_fields: set[str] | None = None,
    default_sort: str = "id",
    supports_batch: bool = False,
    batch_create_dependencies: Sequence[Any] | None = None,
) -> APIRouter:
    router = APIRouter()

    if get_all_dependencies is None:
        get_all_dependencies = []
    if create_dependencies is None:
        create_dependencies = []
    if get_one_dependencies is None:
        get_one_dependencies = []
    if update_dependencies is None:
        update_dependencies = []
    if delete_dependencies is None:
        delete_dependencies = [Depends(get_current_superuser)]
    if restore_dependencies is None:
        restore_dependencies = [Depends(get_current_superuser)]

    if filter_model is not None and supports_restore:
        _filter_sort_dep = get_filter_sort_dependency(
            filter_model, sortable_fields or set(), default_sort
        )

        @router.get(
            "/",
            response_model=Page[read_schema],  # type: ignore[valid-type]
            summary=f"Get all {entity_name}s (paginated)",
            dependencies=get_all_dependencies,
        )
        async def get_all_filtered_soft(
            include_deleted: bool = Query(
                False,
                description="Include soft-deleted records (superuser only)",
            ),
            service: ServiceType = Depends(service_dependency),
            uow: UnitOfWork = Depends(UnitOfWork),
            params: FilterSortParams = Depends(_filter_sort_dep),
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

    elif filter_model is not None:
        _filter_sort_dep = get_filter_sort_dependency(
            filter_model, sortable_fields or set(), default_sort
        )

        @router.get(
            "/",
            response_model=Page[read_schema],  # type: ignore[valid-type]
            summary=f"Get all {entity_name}s (paginated)",
            dependencies=get_all_dependencies,
        )
        async def get_all_filtered(
            service: ServiceType = Depends(service_dependency),
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

    else:

        @router.get(
            "/",
            response_model=Page[read_schema],  # type: ignore[valid-type]
            summary=f"Get all {entity_name}s (paginated)",
            dependencies=get_all_dependencies,
        )
        async def get_all(
            service: ServiceType = Depends(service_dependency),
            uow: UnitOfWork = Depends(UnitOfWork),
            pagination: PaginationParams = Depends(get_pagination_params),
        ) -> Any:
            return await service.get_paginated(
                uow=uow, page=pagination.page, size=pagination.size
            )

    @router.post(
        "/",
        response_model=read_schema,  # type: ignore[valid-type]
        status_code=status.HTTP_201_CREATED,
        summary=f"Create a new {entity_name} (admin only)",
        dependencies=create_dependencies,
        responses={
            **build_error_responses(
                *(create_error_codes or []), UNAUTHORIZED, FORBIDDEN
            ),
        },
    )
    async def create(
        obj_in: create_schema,  # type: ignore[valid-type]
        service: ServiceType = Depends(service_dependency),
        uow: UnitOfWork = Depends(UnitOfWork),
        current_user: User = Depends(get_current_user),
    ) -> Any:
        creator_id = current_user.id
        return await service.create(uow=uow, obj_in=obj_in, creator_id=creator_id)

    if supports_batch:
        _batch_deps = (
            batch_create_dependencies
            if batch_create_dependencies is not None
            else create_dependencies
        )

        @router.post(
            "/batch",
            response_model=BatchCreateResponse[read_schema],  # type: ignore[valid-type]
            status_code=status.HTTP_201_CREATED,
            summary=f"Batch-create {entity_name}s (all-or-nothing)",
            dependencies=_batch_deps,
            responses={
                **build_error_responses(
                    *(create_error_codes or []), UNAUTHORIZED, FORBIDDEN
                ),
            },
        )
        async def create_batch(
            payload: BatchCreateRequest[create_schema],  # type: ignore[valid-type]
            service: ServiceType = Depends(service_dependency),
            uow: UnitOfWork = Depends(UnitOfWork),
            current_user: User = Depends(get_current_user),
        ) -> Any:
            if len(payload.items) > settings.MAX_BATCH_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Batch too large: {len(payload.items)} items; "
                        f"max is {settings.MAX_BATCH_SIZE}"
                    ),
                )
            created = await service.create_many(
                uow=uow, items=payload.items, creator_id=current_user.id
            )
            return BatchCreateResponse(items=created, count=len(created))

    @router.get(
        "/{obj_id}",
        response_model=read_schema,  # type: ignore[valid-type]
        summary=f"Get a {entity_name} by ID",
        dependencies=get_one_dependencies,
        responses={
            **build_error_responses(
                *(get_one_error_codes or []), UNAUTHORIZED, FORBIDDEN
            ),
        },
    )
    async def get_one(
        obj_id: uuid.UUID,
        service: ServiceType = Depends(service_dependency),
        uow: UnitOfWork = Depends(UnitOfWork),
    ) -> Any:
        return await service.get_by_id(uow=uow, obj_id=obj_id)

    @router.put(
        "/{obj_id}",
        response_model=read_schema,  # type: ignore[valid-type]
        summary=f"Update a {entity_name}",
        dependencies=update_dependencies,
        responses={
            **build_error_responses(
                *(update_error_codes or []), UNAUTHORIZED, FORBIDDEN
            ),
        },
    )
    async def update(
        obj_id: uuid.UUID,
        obj_in: update_schema,  # type: ignore[valid-type]
        service: ServiceType = Depends(service_dependency),
        uow: UnitOfWork = Depends(UnitOfWork),
        current_user: User = Depends(get_current_user),
    ) -> Any:
        updater_id = current_user.id
        return await service.update(
            uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=updater_id
        )

    @router.delete(
        "/{obj_id}",
        response_model=read_schema,  # type: ignore[valid-type]
        summary=f"Delete a {entity_name}",
        dependencies=delete_dependencies,
        responses={
            **build_error_responses(
                *(delete_error_codes or []), UNAUTHORIZED, FORBIDDEN
            ),
        },
    )
    async def delete(
        obj_id: uuid.UUID,
        service: ServiceType = Depends(service_dependency),
        uow: UnitOfWork = Depends(UnitOfWork),
        current_user: User = Depends(get_current_user),
    ) -> Any:
        return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)

    if supports_restore:

        @router.post(
            "/{obj_id}/restore",
            response_model=read_schema,  # type: ignore[valid-type]
            summary=f"Restore a deleted {entity_name}",
            dependencies=restore_dependencies,
            responses={
                **build_error_responses(
                    *(restore_error_codes or []), UNAUTHORIZED, FORBIDDEN
                ),
            },
        )
        async def restore(
            obj_id: uuid.UUID,
            service: ServiceType = Depends(service_dependency),
            uow: UnitOfWork = Depends(UnitOfWork),
            current_user: User = Depends(get_current_user),
        ) -> Any:
            return await service.restore(  # type: ignore[attr-defined]
                uow=uow, obj_id=obj_id, restorer_id=current_user.id
            )

    return router
