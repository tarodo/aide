import uuid
from typing import cast

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.credential_ref import CredentialRef
from backend.repositories.credential_ref import CredentialRefRepository
from backend.schemas.credential_ref import (
    CredentialRefCreate,
    CredentialRefRead,
    CredentialRefUpdate,
)
from backend.services.base import GenericService


class CredentialRefService(
    GenericService[
        CredentialRef, CredentialRefCreate, CredentialRefUpdate, CredentialRefRead
    ]
):
    """
    Service for credential reference related business logic.
    """

    def __init__(self):
        super().__init__(
            model=CredentialRef,
            repository=CredentialRefRepository,
            read_schema=CredentialRefRead,
            not_found_error_code=errors.CREDENTIAL_REF_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: CredentialRefCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        repo = cast(CredentialRefRepository, self._get_repository(uow.session))
        if await repo.get_by_provider_and_path(obj_in.provider, obj_in.path):
            raise AppException(errors.CREDENTIAL_REF_ALREADY_EXISTS)

    async def _pre_update(
        self,
        uow: UnitOfWork,
        db_obj: CredentialRef,
        obj_in: CredentialRefUpdate,
        updater_id: uuid.UUID | None,
    ) -> None:
        update_data = obj_in.model_dump(exclude_unset=True)
        repo = cast(CredentialRefRepository, self._get_repository(uow.session))

        current_provider = db_obj.provider
        current_path = db_obj.path
        new_provider = update_data.get("provider", current_provider)
        new_path = update_data.get("path", current_path)

        if new_provider != current_provider or new_path != current_path:
            if await repo.get_by_provider_and_path(new_provider, new_path):
                raise AppException(errors.CREDENTIAL_REF_ALREADY_EXISTS)
