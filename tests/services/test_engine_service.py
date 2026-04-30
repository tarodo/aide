import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models.engine import EngineDebezium, EngineSpark
from backend.schemas.engine import (
    EngineDebeziumUpdate,
    EngineSparkCreate,
)
from backend.services.engine import EngineService


def _mk_uow() -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.session = MagicMock()
    uow.engines = MagicMock()
    uow.dataset_links = MagicMock()
    return uow


def _spark_obj(code: str = "spark-1") -> EngineSparkCreate:
    return EngineSparkCreate(
        kind="spark",
        code=code,
        name="Spark",
        version="3.x",
    )


@pytest.mark.asyncio
async def test_create_dispatches_by_kind(monkeypatch):
    service = EngineService()
    uow = _mk_uow()
    repo = MagicMock()
    repo.get_by_code = AsyncMock(return_value=None)

    captured: list = []

    async def _fake_create(*, obj_in):
        captured.append(obj_in)
        now = datetime.now(UTC)
        obj_in.id = uuid.uuid4()
        obj_in.row_version = 1
        obj_in.created_at = now
        obj_in.updated_at = now
        return obj_in

    repo.create = AsyncMock(side_effect=_fake_create)
    uow.engines = repo

    monkeypatch.setattr(service, "_get_repository", lambda _: repo)

    result = await service.create(uow=uow, obj_in=_spark_obj())
    assert result.kind == "spark"
    assert isinstance(captured[0], EngineSpark)


@pytest.mark.asyncio
async def test_create_rejects_duplicate_code(monkeypatch):
    service = EngineService()
    uow = _mk_uow()
    repo = MagicMock()
    repo.get_by_code = AsyncMock(
        return_value=EngineSpark(
            code="spark-1",
            name="x",
            kind="spark",
            role="compute",
            version="3.x",
        )
    )
    uow.engines = repo
    monkeypatch.setattr(service, "_get_repository", lambda _: repo)

    with pytest.raises(AppException) as exc:
        await service.create(uow=uow, obj_in=_spark_obj())
    assert exc.value.error_code == errors.ENGINE_CODE_ALREADY_EXISTS


@pytest.mark.asyncio
async def test_update_rejects_kind_change(monkeypatch):
    service = EngineService()
    uow = _mk_uow()
    db_obj = EngineDebezium(
        code="dbz-1",
        name="x",
        kind="debezium",
        role="cdc",
        version="2.x",
        envelope_template={"envelope_kind": "debezium", "after_path": "after"},
    )
    db_obj.id = uuid.uuid4()
    repo = MagicMock()
    repo.get = AsyncMock(return_value=db_obj)
    uow.engines = repo
    monkeypatch.setattr(service, "_get_repository", lambda _: repo)

    payload = EngineDebeziumUpdate(kind="debezium", name="renamed", row_version=1)
    payload.kind = "spark"  # type: ignore[assignment]

    with pytest.raises(AppException) as exc:
        await service.update(uow=uow, obj_id=db_obj.id, obj_in=payload)
    assert exc.value.error_code == errors.ENGINE_KIND_IMMUTABLE


@pytest.mark.asyncio
async def test_delete_rejects_when_in_use(monkeypatch):
    service = EngineService()
    uow = _mk_uow()
    db_obj = EngineSpark(
        code="spark-2", name="x", kind="spark", role="compute", version="3.x"
    )
    db_obj.id = uuid.uuid4()
    repo = MagicMock()
    repo.get = AsyncMock(return_value=db_obj)
    uow.engines = repo
    uow.dataset_links.has_active_links_for_engine = AsyncMock(return_value=True)

    monkeypatch.setattr(service, "_get_repository", lambda _: repo)

    with pytest.raises(AppException) as exc:
        await service.delete(uow=uow, obj_id=db_obj.id)
    assert exc.value.error_code == errors.ENGINE_IN_USE
