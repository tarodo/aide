import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.tech_field_template import TechFieldTemplate
from backend.schemas.tech_field_template import (
    TechFieldTemplateCreate,
    TechFieldTemplateRead,
)
from backend.services.tech_field_template import TechFieldTemplateService


class _MockRepo:
    def __init__(self) -> None:
        self.get = AsyncMock()
        self.get_by_code = AsyncMock(return_value=None)
        self.create = AsyncMock()
        self.update = AsyncMock()
        self.delete = AsyncMock()
        self.get_multi_paginated = AsyncMock(return_value=([], 0))


class _MockUoW:
    def __init__(self) -> None:
        self.session = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def service() -> TechFieldTemplateService:
    return TechFieldTemplateService()


@pytest.mark.asyncio
class TestTechFieldTemplateService:
    async def test_create_happy(self, service: TechFieldTemplateService):
        uow = _MockUoW()
        repo = _MockRepo()
        repo.create.return_value = TechFieldTemplate(
            id=uuid.uuid4(),
            code="scd2",
            name="SCD2",
            layer="core",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.create(
                uow=uow,
                obj_in=TechFieldTemplateCreate(code="scd2", name="SCD2", layer="core"),
            )
        assert isinstance(result, TechFieldTemplateRead)
        assert result.code == "scd2"

    async def test_create_duplicate_code(self, service: TechFieldTemplateService):
        uow = _MockUoW()
        repo = _MockRepo()
        repo.get_by_code.return_value = TechFieldTemplate(id=uuid.uuid4(), code="scd2")
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.create(
                    uow=uow,
                    obj_in=TechFieldTemplateCreate(
                        code="scd2", name="SCD2", layer="core"
                    ),
                )
        assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_ALREADY_EXISTS
