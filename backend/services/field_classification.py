import uuid

from backend.core import errors
from backend.core.exceptions import AppException
from backend.db.uow import UnitOfWork
from backend.models.field_classification import FieldClassification
from backend.repositories.field_classification import (
    FieldClassificationRepository,
)
from backend.schemas.field_classification import (
    FieldClassificationCreate,
    FieldClassificationRead,
)
from backend.services.base import GenericService


class FieldClassificationService(
    GenericService[
        FieldClassification,
        FieldClassificationCreate,
        FieldClassificationCreate,  # type: ignore[type-arg]
        FieldClassificationRead,
    ]
):
    """
    Service for append-only field classification entries.

    Update/delete are not supported by design — the router does not register
    those endpoints.
    """

    def __init__(self) -> None:
        super().__init__(
            model=FieldClassification,
            repository=FieldClassificationRepository,
            read_schema=FieldClassificationRead,
            not_found_error_code=errors.FIELD_CLASSIFICATION_NOT_FOUND,
        )

    async def _pre_create(
        self,
        uow: UnitOfWork,
        obj_in: FieldClassificationCreate,
        creator_id: uuid.UUID | None,
    ) -> None:
        if not await uow.fields.get(obj_in.field_id):
            raise AppException(errors.FIELD_NOT_FOUND)
