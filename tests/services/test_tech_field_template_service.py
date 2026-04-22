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
    TechFieldTemplateUpdate,
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

    async def test_update_rename_conflict(self, service: TechFieldTemplateService):
        """Renaming template to a code held by another template is rejected."""
        tpl_id = uuid.uuid4()
        other_id = uuid.uuid4()
        existing = TechFieldTemplate(
            id=tpl_id,
            code="scd2",
            name="SCD2",
            layer="core",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        conflict = TechFieldTemplate(
            id=other_id,
            code="snapshot",
            name="Snapshot",
            layer="core",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        uow = _MockUoW()
        repo = _MockRepo()
        repo.get.return_value = existing
        repo.get_by_code.return_value = conflict
        with patch.object(service, "_get_repository", return_value=repo):
            with pytest.raises(AppException) as exc:
                await service.update(
                    uow=uow,
                    obj_id=tpl_id,
                    obj_in=TechFieldTemplateUpdate(code="snapshot", row_version=1),
                )
        assert exc.value.error_code == errors.TECH_FIELD_TEMPLATE_ALREADY_EXISTS
        repo.update.assert_not_awaited()

    async def test_update_same_code_noop(self, service: TechFieldTemplateService):
        """Updating with unchanged code does not trigger the uniqueness check."""
        tpl_id = uuid.uuid4()
        existing = TechFieldTemplate(
            id=tpl_id,
            code="scd2",
            name="SCD2",
            layer="core",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            row_version=1,
        )
        uow = _MockUoW()
        repo = _MockRepo()
        repo.get.return_value = existing
        repo.update.return_value = existing
        with patch.object(service, "_get_repository", return_value=repo):
            result = await service.update(
                uow=uow,
                obj_id=tpl_id,
                obj_in=TechFieldTemplateUpdate(name="SCD2 v2", row_version=1),
            )
        assert isinstance(result, TechFieldTemplateRead)
        repo.get_by_code.assert_not_awaited()
