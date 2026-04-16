from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from aide_crawler.differ import classify_and_diff
from aide_crawler.normalizer import NormalizedDataset, NormalizedField, NormalizedResult
from aide_crawler.type_cache import TypeCache
from aide_crawler.type_map import TypeChild, TypeNode


def _page(items, pages=1):
    return type("P", (), {"items": items, "pages": pages})()


def _model(**kw):
    """Object that quacks like a pydantic read-model (has .model_dump and .id etc.)."""

    class _M:
        def __init__(self, **k):
            self.__dict__.update(k)

        def model_dump(self):
            return dict(self.__dict__)

    return _M(**kw)


def _nf(name: str, code: str, position: int = 0, children=None) -> NormalizedField:
    return NormalizedField(
        name=name,
        path=name,
        nullable=True,
        position=position,
        type_node=TypeNode(
            data_type_code=code, type_params={}, children=children or []
        ),
    )


def _nd(object_name: str, fields: list[NormalizedField]) -> NormalizedDataset:
    parts = object_name.split(".")
    schema = parts[-2] if len(parts) >= 2 else "public"
    table = parts[-1]
    return NormalizedDataset(
        object_name=object_name,
        catalog_name=parts[0] if len(parts) == 3 else None,
        schema_name=schema,
        table_name=table,
        is_view=False,
        pk_columns=["id"],
        uq_constraints=[],
        comment=None,
        fields=fields,
        indexes=[],
        foreign_keys=[],
    )


class _Cache(TypeCache):
    def __init__(
        self,
        id_to_code: dict[uuid.UUID, str],
        params_schema_by_code: dict[str, dict] | None = None,
    ):
        super().__init__(flavor_code="postgres14")
        self._by_code = {code: id_ for id_, code in id_to_code.items()}
        self._code_by_id = dict(id_to_code)
        self._params_schema_by_code = params_schema_by_code or {}


def _ti_tree(data_type_id, slot=None, type_params=None, children=None):
    return type(
        "T",
        (),
        {
            "id": uuid.uuid4(),
            "data_type_id": data_type_id,
            "slot": slot,
            "type_params": type_params,
            "children": children or [],
        },
    )()


def _build_client(
    *,
    existing_datasets: list,
    existing_fields_by_ds: dict,
    schemas_by_ds: dict,
    bindings_by_schema: dict,
    trees_by_ti: dict,
):
    c = AsyncMock()
    c.datasets = AsyncMock()
    c.datasets.list = AsyncMock(return_value=_page(existing_datasets))

    async def _fields_list(*, page=1, size=100, params=None):
        ds_id = params["dataset_id"]
        return _page(existing_fields_by_ds.get(ds_id, []))

    c.fields = AsyncMock()
    c.fields.list = AsyncMock(side_effect=_fields_list)

    async def _schemas_list(*, page=1, size=100, params=None):
        ds_id = params["dataset_id"]
        return _page(schemas_by_ds.get(ds_id, []))

    c.dataset_schemas = AsyncMock()
    c.dataset_schemas.list = AsyncMock(side_effect=_schemas_list)

    async def _bindings_list(*, page=1, size=100, params=None):
        schema_id = params["dataset_schema_id"]
        return _page(bindings_by_schema.get(schema_id, []))

    c.field_bindings = AsyncMock()
    c.field_bindings.list = AsyncMock(side_effect=_bindings_list)

    async def _get_tree(ti_id):
        from aide_sdk.exceptions import NotFoundError

        tree = trees_by_ti.get(ti_id)
        if tree is None:
            raise NotFoundError(
                status_code=404, error_code="NOT_FOUND", detail=str(ti_id)
            )
        return tree

    c.type_instances = AsyncMock()
    c.type_instances.get_tree = AsyncMock(side_effect=_get_tree)

    return c


SYSTEM_ID = uuid.uuid4()


@pytest.mark.asyncio
async def test_unchanged_field_produces_no_type_change():
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    field_id = uuid.uuid4()
    ti_id = uuid.uuid4()
    dt_int = uuid.uuid4()

    cache = _Cache({dt_int: "integer"})

    client = _build_client(
        existing_datasets=[
            _model(id=ds_id, object_name="target.demo.t"),
        ],
        existing_fields_by_ds={str(ds_id): [_model(id=field_id, name="id")]},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=field_id, type_instance_id=ti_id)]
        },
        trees_by_ti={ti_id: _ti_tree(dt_int)},
    )

    nd = _nd("target.demo.t", [_nf("id", "integer")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    entry = payload.existing_datasets_diff[0]
    assert entry["type_changes"] == []
    assert entry["new_fields"] == []
    assert entry["removed_fields"] == []


@pytest.mark.asyncio
async def test_varchar_to_text_reports_type_change():
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    field_id = uuid.uuid4()
    ti_id = uuid.uuid4()
    dt_varchar = uuid.uuid4()
    dt_text = uuid.uuid4()

    cache = _Cache(
        {dt_varchar: "varchar", dt_text: "text"},
        params_schema_by_code={"varchar": {"length": {"type": "int"}}, "text": {}},
    )

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): [_model(id=field_id, name="name")]},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=field_id, type_instance_id=ti_id)]
        },
        trees_by_ti={ti_id: _ti_tree(dt_varchar, type_params={"length": 255})},
    )

    nd = _nd("target.demo.t", [_nf("name", "text")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    changes = payload.existing_datasets_diff[0]["type_changes"]
    assert len(changes) == 1
    change = changes[0]
    assert change["field_name"] == "name"
    assert change["before"] == {"code": "varchar", "params": {"length": 255}}
    assert change["after"] == {"code": "text", "params": {}}


@pytest.mark.asyncio
async def test_array_element_change_reports_type_change():
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    field_id = uuid.uuid4()
    root_ti = uuid.uuid4()
    dt_array = uuid.uuid4()
    dt_int = uuid.uuid4()
    dt_bigint = uuid.uuid4()

    cache = _Cache({dt_array: "array", dt_int: "integer", dt_bigint: "bigint"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): [_model(id=field_id, name="nums")]},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=field_id, type_instance_id=root_ti)]
        },
        trees_by_ti={
            root_ti: _ti_tree(
                dt_array,
                children=[_ti_tree(dt_int, slot="item")],
            )
        },
    )

    nd = _nd(
        "target.demo.t",
        [
            _nf(
                "nums",
                "array",
                children=[
                    TypeChild(
                        slot="item",
                        node=TypeNode(data_type_code="bigint", type_params={}),
                    )
                ],
            )
        ],
    )
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    changes = payload.existing_datasets_diff[0]["type_changes"]
    assert len(changes) == 1
    assert changes[0]["before"] == {"code": "array", "params": {}}
    assert changes[0]["after"] == {"code": "array", "params": {}}
    assert changes[0]["full_before"]["children"][0]["node"]["code"] == "integer"
    assert changes[0]["full_after"]["children"][0]["node"]["code"] == "bigint"


@pytest.mark.asyncio
async def test_added_field_is_new_not_type_change():
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    cache = _Cache({uuid.uuid4(): "integer"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): []},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={str(schema_id): []},
        trees_by_ti={},
    )

    nd = _nd("target.demo.t", [_nf("id", "integer")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    entry = payload.existing_datasets_diff[0]
    assert entry["new_fields"][0]["name"] == "id"
    assert entry["type_changes"] == []


@pytest.mark.asyncio
async def test_missing_type_instance_reported_as_missing():
    """get_tree → NotFoundError must not abort the diff; field is marked __missing__."""
    from aide_sdk.exceptions import NotFoundError

    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    field_id = uuid.uuid4()
    ti_id = uuid.uuid4()
    dt_int = uuid.uuid4()

    cache = _Cache({dt_int: "integer"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={str(ds_id): [_model(id=field_id, name="id")]},
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=field_id, type_instance_id=ti_id)]
        },
        trees_by_ti={},
    )
    client.type_instances.get_tree = AsyncMock(
        side_effect=NotFoundError(status_code=404, error_code="X", detail="gone")
    )

    nd = _nd("target.demo.t", [_nf("id", "integer")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    changes = payload.existing_datasets_diff[0]["type_changes"]
    assert len(changes) == 1
    assert changes[0]["before"] == {"code": "__missing__", "params": {}}
    assert changes[0]["after"] == {"code": "integer", "params": {}}


@pytest.mark.asyncio
async def test_all_new_datasets_go_to_apply():
    """No matching dataset in metastore → routed to to_apply, not to existing diff."""
    cache = _Cache({})

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={},
        bindings_by_schema={},
        trees_by_ti={},
    )

    nd = _nd("target.demo.t", [_nf("id", "integer")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    to_apply, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    assert [d.object_name for d in to_apply] == ["target.demo.t"]
    assert payload.existing_datasets_diff == []
    assert payload.removed_datasets == []


@pytest.mark.asyncio
async def test_removed_dataset_listed():
    """Dataset present in metastore but absent in crawl → removed_datasets."""
    ds_id = uuid.uuid4()
    cache = _Cache({})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.gone")],
        existing_fields_by_ds={},
        schemas_by_ds={},
        bindings_by_schema={},
        trees_by_ti={},
    )

    normalized = NormalizedResult(dialect_name="postgresql", datasets=[])

    to_apply, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    assert to_apply == []
    assert len(payload.removed_datasets) == 1
    assert payload.removed_datasets[0]["object_name"] == "target.demo.gone"
    assert payload.removed_datasets[0]["dataset_id"] == str(ds_id)


@pytest.mark.asyncio
async def test_existing_with_removed_field():
    """Field present in metastore but absent in crawl → removed_fields entry."""
    ds_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    drop_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    dt_int = uuid.uuid4()

    cache = _Cache({dt_int: "integer"})

    client = _build_client(
        existing_datasets=[_model(id=ds_id, object_name="target.demo.t")],
        existing_fields_by_ds={
            str(ds_id): [
                _model(id=keep_id, name="id"),
                _model(id=drop_id, name="legacy"),
            ]
        },
        schemas_by_ds={str(ds_id): [_model(id=schema_id, version_num=1)]},
        bindings_by_schema={
            str(schema_id): [_model(field_id=keep_id, type_instance_id=keep_ti)]
        },
        trees_by_ti={keep_ti: _ti_tree(dt_int)},
    )

    nd = _nd("target.demo.t", [_nf("id", "integer")])
    normalized = NormalizedResult(dialect_name="postgresql", datasets=[nd])

    _, payload = await classify_and_diff(client, SYSTEM_ID, normalized, cache)
    entry = payload.existing_datasets_diff[0]
    assert entry["new_fields"] == []
    assert [rf["name"] for rf in entry["removed_fields"]] == ["legacy"]
    assert entry["removed_fields"][0]["field_id"] == str(drop_id)
    assert entry["type_changes"] == []


def test_diff_payload_to_dict_carries_schema_version():
    from aide_crawler.differ import DiffPayload

    payload = DiffPayload()
    out = payload.to_dict()
    assert out["schema_version"] == 1
    assert out["new_datasets_applied"] == []
    assert out["existing_datasets_diff"] == []
    assert out["removed_datasets"] == []


def test_diff_payload_counts_aggregates_all_axes():
    from aide_crawler.differ import DiffPayload

    payload = DiffPayload(
        new_datasets_applied=[{"object_name": "a"}, {"object_name": "b"}],
        existing_datasets_diff=[
            {
                "new_fields": [{"name": "x"}, {"name": "y"}],
                "removed_fields": [{"name": "z"}],
                "type_changes": [{"field_name": "q"}],
            }
        ],
        removed_datasets=[{"object_name": "c"}],
    )
    counts = payload.counts()
    assert counts == {
        "new_datasets_applied": 2,
        "new_fields": 2,
        "removed_fields": 1,
        "removed_datasets": 1,
        "type_changes": 1,
    }


# ---------------------------------------------------------------------------
# Baseline + max-version helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_baseline_schema_picks_latest_with_bindings():
    """Two versions, both with bindings → baseline is the higher version_num."""
    from aide_crawler.differ import _find_baseline_schema

    ds_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()
    field_id = uuid.uuid4()

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={
            str(ds_id): [
                _model(id=v1_id, version_num=1),
                _model(id=v2_id, version_num=2),
            ]
        },
        bindings_by_schema={
            str(v1_id): [_model(field_id=field_id, type_instance_id=uuid.uuid4())],
            str(v2_id): [_model(field_id=field_id, type_instance_id=uuid.uuid4())],
        },
        trees_by_ti={},
    )

    result = await _find_baseline_schema(client, ds_id)
    assert result == (v2_id, 2)


@pytest.mark.asyncio
async def test_find_baseline_schema_skips_orphan():
    """v1 has bindings, v2 is orphan (no bindings) → baseline is v1."""
    from aide_crawler.differ import _find_baseline_schema

    ds_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()
    field_id = uuid.uuid4()

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={
            str(ds_id): [
                _model(id=v1_id, version_num=1),
                _model(id=v2_id, version_num=2),
            ]
        },
        bindings_by_schema={
            str(v1_id): [_model(field_id=field_id, type_instance_id=uuid.uuid4())],
            str(v2_id): [],
        },
        trees_by_ti={},
    )

    result = await _find_baseline_schema(client, ds_id)
    assert result == (v1_id, 1)


@pytest.mark.asyncio
async def test_find_baseline_schema_returns_none_when_all_orphan():
    """Every version has zero bindings → None."""
    from aide_crawler.differ import _find_baseline_schema

    ds_id = uuid.uuid4()
    v1_id = uuid.uuid4()

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={str(ds_id): [_model(id=v1_id, version_num=1)]},
        bindings_by_schema={str(v1_id): []},
        trees_by_ti={},
    )

    result = await _find_baseline_schema(client, ds_id)
    assert result is None


@pytest.mark.asyncio
async def test_find_baseline_schema_returns_none_when_no_schemas():
    """Dataset has no DatasetSchema rows at all → None."""
    from aide_crawler.differ import _find_baseline_schema

    ds_id = uuid.uuid4()

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={str(ds_id): []},
        bindings_by_schema={},
        trees_by_ti={},
    )

    result = await _find_baseline_schema(client, ds_id)
    assert result is None


@pytest.mark.asyncio
async def test_find_max_version_num_returns_highest_across_all():
    """Max is computed over ALL rows, including orphans above the baseline."""
    from aide_crawler.differ import _find_max_version_num

    ds_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()  # orphan (no bindings)
    v5_id = uuid.uuid4()  # orphan (no bindings)

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={
            str(ds_id): [
                _model(id=v1_id, version_num=1),
                _model(id=v2_id, version_num=2),
                _model(id=v5_id, version_num=5),
            ]
        },
        bindings_by_schema={},
        trees_by_ti={},
    )

    result = await _find_max_version_num(client, ds_id)
    assert result == 5


@pytest.mark.asyncio
async def test_find_max_version_num_returns_zero_when_no_schemas():
    """No rows → 0 (so next allocation starts at 1)."""
    from aide_crawler.differ import _find_max_version_num

    ds_id = uuid.uuid4()

    client = _build_client(
        existing_datasets=[],
        existing_fields_by_ds={},
        schemas_by_ds={str(ds_id): []},
        bindings_by_schema={},
        trees_by_ti={},
    )

    result = await _find_max_version_num(client, ds_id)
    assert result == 0
