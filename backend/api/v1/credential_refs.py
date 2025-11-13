from fastapi import APIRouter

from backend.api.v1.utils.crud_router import create_crud_router
from backend.core.errors import (
    CREDENTIAL_REF_ALREADY_EXISTS,
    CREDENTIAL_REF_NOT_FOUND,
)
from backend.schemas.credential_ref import (
    CredentialRefCreate,
    CredentialRefRead,
    CredentialRefUpdate,
)
from backend.services.credential_ref import CredentialRefService

router = APIRouter()

crud_router = create_crud_router(
    service_dependency=CredentialRefService,
    create_schema=CredentialRefCreate,
    update_schema=CredentialRefUpdate,
    read_schema=CredentialRefRead,
    entity_name="credential ref",
    create_error_codes=[CREDENTIAL_REF_ALREADY_EXISTS],
    update_error_codes=[CREDENTIAL_REF_NOT_FOUND, CREDENTIAL_REF_ALREADY_EXISTS],
    get_one_error_codes=[CREDENTIAL_REF_NOT_FOUND],
    delete_error_codes=[CREDENTIAL_REF_NOT_FOUND],
)

router.include_router(crud_router)
