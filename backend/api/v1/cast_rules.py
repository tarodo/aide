from fastapi import APIRouter

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    CAST_RULE_ALREADY_EXISTS,
    CAST_RULE_NOT_FOUND,
    DATA_TYPE_NOT_FOUND,
)
from backend.schemas.cast_rule import (
    CastRuleCreate,
    CastRuleRead,
    CastRuleUpdate,
)
from backend.schemas.filters import CAST_RULE_SORTABLE, CastRuleFilter
from backend.services.cast_rule import CastRuleService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=CastRuleService,
    create_schema=CastRuleCreate,
    update_schema=CastRuleUpdate,
    read_schema=CastRuleRead,
    entity_name="cast rule",
    create_error_codes=[CAST_RULE_ALREADY_EXISTS, DATA_TYPE_NOT_FOUND],
    update_error_codes=[
        CAST_RULE_NOT_FOUND,
        CAST_RULE_ALREADY_EXISTS,
        DATA_TYPE_NOT_FOUND,
    ],
    get_one_error_codes=[CAST_RULE_NOT_FOUND],
    delete_error_codes=[CAST_RULE_NOT_FOUND],
    filter_model=CastRuleFilter,
    sortable_fields=CAST_RULE_SORTABLE,
)

router.include_router(crud_router)
