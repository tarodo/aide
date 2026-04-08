import uuid
from typing import Any, List, Sequence, Type, TypeVar

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from backend.api.dependencies import (
    PaginationParams,
    get_current_superuser,
    get_current_user,
    get_pagination_params,
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
