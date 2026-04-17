from fastapi import APIRouter

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    FIELD_CLASSIFICATION_NOT_FOUND,
    FIELD_NOT_FOUND,
)
from backend.schemas.field_classification import (
    FieldClassificationCreate,
    FieldClassificationRead,
)
from backend.schemas.filters import (
    FIELD_CLASSIFICATION_SORTABLE,
    FieldClassificationFilter,
)
from backend.services.field_classification import FieldClassificationService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=FieldClassificationService,
    create_schema=FieldClassificationCreate,
    update_schema=None,
    read_schema=FieldClassificationRead,
    entity_name="field classification",
    create_error_codes=[FIELD_NOT_FOUND],
    get_one_error_codes=[FIELD_CLASSIFICATION_NOT_FOUND],
    filter_model=FieldClassificationFilter,
    sortable_fields=FIELD_CLASSIFICATION_SORTABLE,
    default_sort="-created_at",
    supports_update=False,
    supports_delete=False,
)

router.include_router(crud_router)
