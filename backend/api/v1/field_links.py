import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_current_superuser, get_current_user
from backend.core.errors import (
    DATASET_LINK_NOT_FOUND,
    FIELD_LINK_ALREADY_EXISTS,
    FIELD_LINK_NOT_FOUND,
    FIELD_LINK_SOURCE_DATASET_MISMATCH,
    FIELD_LINK_TARGET_DATASET_MISMATCH,
    FIELD_LINK_TARGET_OCCUPIED,
    FIELD_NON_TECH_REQUIRES_SOURCE,
    FIELD_NOT_FOUND,
    FORBIDDEN,
    UNAUTHORIZED,
    VERSION_CONFLICT,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.field_link import (
    FieldLinkCreate,
    FieldLinkRead,
    FieldLinkUpdate,
)
from backend.services.field_link import FieldLinkService

router = APIRouter()


@router.get(
    "/dataset-links/{dataset_link_id}/field-links/",
    response_model=list[FieldLinkRead],
    responses={**build_error_responses(UNAUTHORIZED, FORBIDDEN)},
)
async def list_by_dataset_link(
    dataset_link_id: uuid.UUID,
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    async with uow:
        items = await uow.field_links.list_by_dataset_link(dataset_link_id)
        return [FieldLinkRead.model_validate(it) for it in items]


@router.post(
    "/dataset-links/{dataset_link_id}/field-links/",
    response_model=FieldLinkRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_LINK_NOT_FOUND,
            FIELD_NOT_FOUND,
            FIELD_LINK_ALREADY_EXISTS,
            FIELD_LINK_SOURCE_DATASET_MISMATCH,
            FIELD_LINK_TARGET_DATASET_MISMATCH,
            FIELD_LINK_TARGET_OCCUPIED,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def create_field_link(
    dataset_link_id: uuid.UUID,
    obj_in: FieldLinkCreate,
    service: FieldLinkService = Depends(FieldLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    obj_in = obj_in.model_copy(update={"dataset_link_id": dataset_link_id})
    return await service.create(uow=uow, obj_in=obj_in, creator_id=current_user.id)


@router.post(
    "/dataset-links/{dataset_link_id}/field-links/bulk",
    response_model=list[FieldLinkRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            DATASET_LINK_NOT_FOUND,
            FIELD_NOT_FOUND,
            FIELD_LINK_ALREADY_EXISTS,
            FIELD_LINK_SOURCE_DATASET_MISMATCH,
            FIELD_LINK_TARGET_DATASET_MISMATCH,
            FIELD_LINK_TARGET_OCCUPIED,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def bulk_create_field_links(
    dataset_link_id: uuid.UUID,
    items: list[FieldLinkCreate],
    service: FieldLinkService = Depends(FieldLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    items = [it.model_copy(update={"dataset_link_id": dataset_link_id}) for it in items]
    return await service.bulk_create(uow=uow, items=items, creator_id=current_user.id)


@router.patch(
    "/field-links/{obj_id}",
    response_model=FieldLinkRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            FIELD_LINK_NOT_FOUND, VERSION_CONFLICT, UNAUTHORIZED, FORBIDDEN
        ),
    },
)
async def update_field_link(
    obj_id: uuid.UUID,
    obj_in: FieldLinkUpdate,
    service: FieldLinkService = Depends(FieldLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.update(
        uow=uow, obj_id=obj_id, obj_in=obj_in, updater_id=current_user.id
    )


@router.delete(
    "/field-links/{obj_id}",
    response_model=FieldLinkRead,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            FIELD_LINK_NOT_FOUND,
            FIELD_NON_TECH_REQUIRES_SOURCE,
            UNAUTHORIZED,
            FORBIDDEN,
        ),
    },
)
async def delete_field_link(
    obj_id: uuid.UUID,
    service: FieldLinkService = Depends(FieldLinkService),
    uow: UnitOfWork = Depends(UnitOfWork),
    current_user: User = Depends(get_current_user),
) -> Any:
    return await service.delete(uow=uow, obj_id=obj_id, deleter_id=current_user.id)
