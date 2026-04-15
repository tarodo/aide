import uuid
from unittest.mock import AsyncMock, patch

import pytest

from aide_crawler.runner import run_crawl


def _page(items, pages=1, total=None):
    return type(
        "P",
        (),
        {
            "items": items,
            "pages": pages,
            "total": total if total is not None else len(items),
        },
    )()


def _obj(**kw):
    return type("O", (), kw)()


@pytest.mark.asyncio
async def test_runner_happy_path_empty_inspection(monkeypatch):
    system_id = uuid.uuid4()
    flavor_id = uuid.uuid4()
    crawl_run_id = uuid.uuid4()

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    client.systems = AsyncMock()
    client.systems.list = AsyncMock(
        return_value=_page([_obj(id=system_id, flavor_id=flavor_id)], total=1)
    )
    client.data_types = AsyncMock()
    # First call (total check), second call (TypeCache.load)
    client.data_types.list = AsyncMock(
        side_effect=[
            _page([_obj(id=uuid.uuid4(), code="bigint", params_schema={})], total=1),
            _page(
                [_obj(id=uuid.uuid4(), code="bigint", params_schema={})],
                pages=1,
                total=1,
            ),
        ]
    )
    client.crawl_runs = AsyncMock()
    client.crawl_runs.create = AsyncMock(
        return_value=_obj(id=crawl_run_id, row_version=0)
    )
    client.crawl_runs.update = AsyncMock()

    from aide_crawler.differ import DiffPayload

    monkeypatch.setattr(
        "aide_crawler.runner.run_inspection",
        lambda *a, **k: _obj(dialect_name="postgresql", tables=[]),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.normalize",
        lambda _: _obj(dialect_name="postgresql", datasets=[]),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.classify_and_diff",
        AsyncMock(return_value=([], DiffPayload())),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.apply_new_datasets", AsyncMock(return_value=[])
    )
    monkeypatch.setattr("aide_crawler.runner.format_report", lambda *a, **k: None)

    with patch("aide_crawler.runner.AideClient", return_value=client):
        await run_crawl(
            system_code="sys",
            connection_url="postgresql://x",
            metastore_url="http://m",
            metastore_user="u",
            metastore_password="p",
        )

    update_args, update_kwargs = client.crawl_runs.update.await_args
    assert update_args[0] == crawl_run_id
    update_payload = update_args[1]
    assert update_payload.status.value == "completed"
    assert update_payload.diff_payload["schema_version"] == 1


@pytest.mark.asyncio
async def test_runner_no_data_types_raises_system_exit(monkeypatch):
    system_id = uuid.uuid4()
    flavor_id = uuid.uuid4()

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    client.systems = AsyncMock()
    client.systems.list = AsyncMock(
        return_value=_page([_obj(id=system_id, flavor_id=flavor_id)], total=1)
    )
    client.data_types = AsyncMock()
    client.data_types.list = AsyncMock(return_value=_page([], total=0))

    with patch("aide_crawler.runner.AideClient", return_value=client):
        with pytest.raises(SystemExit):
            await run_crawl(
                system_code="sys",
                connection_url="postgresql://x",
                metastore_url="http://m",
                metastore_user="u",
                metastore_password="p",
            )


@pytest.mark.asyncio
async def test_runner_failure_updates_crawl_run(monkeypatch):
    system_id = uuid.uuid4()
    flavor_id = uuid.uuid4()
    crawl_run_id = uuid.uuid4()

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    client.systems = AsyncMock()
    client.systems.list = AsyncMock(
        return_value=_page([_obj(id=system_id, flavor_id=flavor_id)], total=1)
    )
    client.data_types = AsyncMock()
    client.data_types.list = AsyncMock(
        side_effect=[
            _page([_obj(id=uuid.uuid4(), code="bigint", params_schema={})], total=1),
            _page([_obj(id=uuid.uuid4(), code="bigint", params_schema={})], total=1),
        ]
    )
    client.crawl_runs = AsyncMock()
    client.crawl_runs.create = AsyncMock(
        return_value=_obj(id=crawl_run_id, row_version=0)
    )
    client.crawl_runs.update = AsyncMock()

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("aide_crawler.runner.run_inspection", boom)

    with patch("aide_crawler.runner.AideClient", return_value=client):
        with pytest.raises(RuntimeError, match="kaboom"):
            await run_crawl(
                system_code="sys",
                connection_url="postgresql://x",
                metastore_url="http://m",
                metastore_user="u",
                metastore_password="p",
            )

    update_args, _ = client.crawl_runs.update.await_args
    payload = update_args[1]
    assert payload.status.value == "failed"
    assert "kaboom" in payload.error_message
