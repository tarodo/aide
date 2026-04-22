import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.tech_field_template import TechFieldTemplateField
from backend.schemas.tech_field_template import (
    TechFieldTemplateFieldCreate,
    TechFieldTemplateFieldRead,
)
from backend.services.tech_field_template_field import (
    TechFieldTemplateFieldService,
)


class _MockRepo:
    def __init__(self) -> None:
        self.get = AsyncMock()
        self.get_by_template_and_name = AsyncMock(return_value=None)
        self.list_by_template = AsyncMock(return_value=[])
        self.create = AsyncMock()
        self.update = AsyncMock()
        self.delete = AsyncMock()
        self.get_multi_paginated = AsyncMock(return_value=([], 0))


class _MockUoW:
    def __init__(self) -> None:
        self.session = AsyncMock()
        self.tech_field_templates = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def service() -> TechFieldTemplateFieldService:
    return TechFieldTemplateFieldService()


@pytest.mark.asyncio
class TestTechFieldTemplateFieldService:
    async def test_create_happy(self, service: TechFieldTemplateFieldService):
        template_id = uuid.uuid4()
        uow = _MockUoW()
        uow.tech_field_templates.get.return_value = object()  # truthy — template exists
        repo = _MockRepo()
        repo.create.return_value = TechFieldTemplateField(
            id=uuid.uuid4(),
            template_id=template_id,
            name="valid_from",
            type_code="TIMESTAMP",
            order=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=TechFieldTemplateFieldCreate(
                    template_id=template_id,
                    name="valid_from",
                    type_code="TIMESTAMP",
                    order=0,
                ),
            )
        assert isinstance(result, TechFieldTemplateFieldRead)
        assert result.name == "valid_from"

    async def test_create_template_missing(
        self, service: TechFieldTemplateFieldService
    ):
        template_id = uuid.uuid4()
        uow = _MockUoW()
        uow.tech_field_templates.get.return_value = None
        repo = _MockRepo()
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=TechFieldTemplateFieldCreate(
                        template_id=template_id,
                        name="x",
                        type_code="STRING",
                        order=0,
                    ),
                )
        assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_NOT_FOUND

    async def test_create_duplicate_name(self, service: TechFieldTemplateFieldService):
        template_id = uuid.uuid4()
        uow = _MockUoW()
        uow.tech_field_templates.get.return_value = object()
        repo = _MockRepo()
        repo.get_by_template_and_name.return_value = TechFieldTemplateField(
            id=uuid.uuid4(), template_id=template_id, name="dup"
        )
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=TechFieldTemplateFieldCreate(
                        template_id=template_id,
                        name="dup",
                        type_code="STRING",
                        order=0,
                    ),
                )
        assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS
