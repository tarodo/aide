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
    def __init__(self, id_to_code: dict[uuid.UUID, str]):
        super().__init__(flavor_code="postgres14")
        self._by_code = {code: id_ for id_, code in id_to_code.items()}
        self._code_by_id = dict(id_to_code)


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
        return trees_by_ti[ti_id]

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

    cache = _Cache({dt_varchar: "varchar", dt_text: "text"})

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
