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
        AsyncMock(return_value=([], [], DiffPayload())),
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


@pytest.mark.asyncio
async def test_runner_calls_versioned_apply_when_to_version_nonempty(monkeypatch):
    """to_version non-empty → apply_versioned_datasets called; summary extended."""
    system_id = uuid.uuid4()
    flavor_id = uuid.uuid4()
    crawl_run_id = uuid.uuid4()
    ds_id = uuid.uuid4()
    new_schema_id = uuid.uuid4()

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

    from aide_crawler.applier import VersionedDataset
    from aide_crawler.differ import DiffPayload, VersionedDatasetPlan

    plan = VersionedDatasetPlan(
        dataset_id=ds_id,
        object_name="public.orders",
        current_version_num=1,
        next_version_num=2,
        all_fields=[],
        unchanged_field_bindings={},
        added_fields=[],
        type_changed_fields=[],
        removed_field_ids=[],
    )
    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "public.orders",
                "dataset_id": str(ds_id),
                "current_version_num": 1,
                "new_version_num": None,
                "new_fields": [{"name": "status", "code": "varchar", "params": {}}],
                "removed_fields": [],
                "type_changes": [],
            }
        ]
    )

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
        AsyncMock(return_value=([], [plan], payload)),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.apply_new_datasets", AsyncMock(return_value=[])
    )
    versioned_result = [
        VersionedDataset(
            dataset_id=ds_id,
            object_name="public.orders",
            dataset_schema_id=new_schema_id,
            old_version_num=1,
            new_version_num=2,
            fields_added=1,
            fields_removed=0,
            type_changes=0,
        )
    ]
    apply_versioned_mock = AsyncMock(return_value=versioned_result)
    monkeypatch.setattr(
        "aide_crawler.runner.apply_versioned_datasets", apply_versioned_mock
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

    apply_versioned_mock.assert_awaited_once()
    call_kwargs = apply_versioned_mock.await_args.kwargs
    assert call_kwargs["plans"] == [plan]

    update_args, _ = client.crawl_runs.update.await_args
    update_payload = update_args[1]
    assert update_payload.status.value == "completed"
    assert update_payload.summary["new_versions_created"] == 1
    assert len(update_payload.summary["versioned_datasets"]) == 1
    vd_entry = update_payload.summary["versioned_datasets"][0]
    assert vd_entry["object_name"] == "public.orders"
    assert vd_entry["old_version"] == 1
    assert vd_entry["new_version"] == 2
    assert vd_entry["added"] == 1
    # DiffPayload entry's new_version_num is filled in post-apply
    diff_entry = update_payload.diff_payload["existing_datasets_diff"][0]
    assert diff_entry["new_version_num"] == 2


@pytest.mark.asyncio
async def test_runner_skips_versioned_apply_when_to_version_empty(monkeypatch):
    """Empty to_version → apply_versioned_datasets called with empty list;
    summary shows new_versions_created=0."""
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
        AsyncMock(return_value=([], [], DiffPayload())),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.apply_new_datasets", AsyncMock(return_value=[])
    )
    apply_versioned_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "aide_crawler.runner.apply_versioned_datasets", apply_versioned_mock
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

    update_args, _ = client.crawl_runs.update.await_args
    update_payload = update_args[1]
    assert update_payload.summary["new_versions_created"] == 0
    assert update_payload.summary["versioned_datasets"] == []


@pytest.mark.asyncio
async def test_runner_warns_on_orphan_only_existing_dataset(monkeypatch, caplog):
    """DiffPayload entry with current_version_num=None → runner logs a warning."""
    import logging

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

    payload = DiffPayload(
        existing_datasets_diff=[
            {
                "object_name": "public.orphan",
                "dataset_id": str(uuid.uuid4()),
                "current_version_num": None,
                "new_version_num": None,
                "new_fields": [],
                "removed_fields": [],
                "type_changes": [],
            }
        ]
    )
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
        AsyncMock(return_value=([], [], payload)),
    )
    monkeypatch.setattr(
        "aide_crawler.runner.apply_new_datasets", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "aide_crawler.runner.apply_versioned_datasets",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr("aide_crawler.runner.format_report", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING, logger="aide_crawler.runner"):
        with patch("aide_crawler.runner.AideClient", return_value=client):
            await run_crawl(
                system_code="sys",
                connection_url="postgresql://x",
                metastore_url="http://m",
                metastore_user="u",
                metastore_password="p",
            )

    assert any("public.orphan" in rec.message for rec in caplog.records)
    assert any("orphan" in rec.message.lower() for rec in caplog.records)
