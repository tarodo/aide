import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_current_superuser
from backend.core.errors import (
    DATA_TYPE_NOT_FOUND,
    DATASET_ALREADY_EXISTS,
    DATASET_NOT_FOUND,
    FORBIDDEN,
    LAKE_SYNC_AMBIGUOUS_CAST,
    LAKE_SYNC_NO_SOURCE_SCHEMA,
    LAKE_SYNC_TARGET_FLAVOR_MISMATCH,
    LAKE_SYNC_UNKNOWN_OVERRIDE_FIELD,
    SYSTEM_FLAVOR_NOT_FOUND,
    SYSTEM_NOT_FOUND,
    TECH_FIELD_TEMPLATE_LAYER_MISMATCH,
    TECH_FIELD_TEMPLATE_NOT_FOUND,
    TECH_TYPE_CODE_NOT_RESOLVABLE,
    UNAUTHORIZED,
    build_error_responses,
)
from backend.db.uow import UnitOfWork
from backend.models import User
from backend.schemas.lake_sync import LakeSyncRequest, LakeSyncResponse
from backend.services.lake_sync import LakeSyncService

router = APIRouter()


@router.post(
    "/datasets/{source_dataset_id}/lake-sync",
    response_model=LakeSyncResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
    responses={
        **build_error_responses(
            UNAUTHORIZED,
            FORBIDDEN,
            DATASET_NOT_FOUND,
            DATASET_ALREADY_EXISTS,
            SYSTEM_NOT_FOUND,
            SYSTEM_FLAVOR_NOT_FOUND,
            DATA_TYPE_NOT_FOUND,
            TECH_FIELD_TEMPLATE_NOT_FOUND,
            TECH_FIELD_TEMPLATE_LAYER_MISMATCH,
            TECH_TYPE_CODE_NOT_RESOLVABLE,
            LAKE_SYNC_NO_SOURCE_SCHEMA,
            LAKE_SYNC_TARGET_FLAVOR_MISMATCH,
            LAKE_SYNC_UNKNOWN_OVERRIDE_FIELD,
            LAKE_SYNC_AMBIGUOUS_CAST,
        ),
    },
)
async def create_lake_target(
    source_dataset_id: uuid.UUID,
    request: LakeSyncRequest,
    current_user: User = Depends(get_current_superuser),
    service: LakeSyncService = Depends(LakeSyncService),
    uow: UnitOfWork = Depends(UnitOfWork),
) -> Any:
    return await service.create_lake_target(
        uow=uow,
        source_dataset_id=source_dataset_id,
        request=request,
        applier_id=current_user.id,
    )
