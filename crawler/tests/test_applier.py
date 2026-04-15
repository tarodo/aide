from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from aide_crawler.applier import AppliedDataset, apply_new_datasets
from aide_crawler.normalizer import NormalizedDataset, NormalizedField
from aide_crawler.type_cache import TypeCache
from aide_crawler.type_map import TypeMapping

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _page(items, pages=1):
    return type("P", (), {"items": items, "pages": pages})()


def _obj(**kw):
    return type("O", (), kw)()


def _mock_client(
    *,
    fields_map: dict[str, uuid.UUID] | None = None,
    schemas: list | None = None,
    bindings_field_ids: list[uuid.UUID] | None = None,
):
    c = AsyncMock()

    c.datasets = AsyncMock()
    c.datasets.create = AsyncMock(side_effect=lambda _p: _obj(id=uuid.uuid4()))

    c.dataset_schemas = AsyncMock()
    c.dataset_schemas.list = AsyncMock(return_value=_page(schemas or []))
    c.dataset_schemas.create = AsyncMock(side_effect=lambda _p: _obj(id=uuid.uuid4()))

    c.fields = AsyncMock()
    c.fields.list = AsyncMock(
        return_value=_page(
            [_obj(id=fid, name=fn) for fn, fid in (fields_map or {}).items()]
        )
    )
    c.fields.create = AsyncMock(
        side_effect=lambda p: _obj(id=uuid.uuid4(), name=p.name)
    )

    c.type_instances = AsyncMock()
    c.type_instances.create = AsyncMock(side_effect=lambda _p: _obj(id=uuid.uuid4()))

    c.field_bindings = AsyncMock()
    c.field_bindings.list = AsyncMock(
        return_value=_page([_obj(field_id=fid) for fid in (bindings_field_ids or [])])
    )
    c.field_bindings.create = AsyncMock(side_effect=lambda _p: _obj(id=uuid.uuid4()))

    return c


def _nf(
    name: str,
    code: str = "bigint",
    position: int = 0,
    nullable: bool = False,
    params: dict | None = None,
) -> NormalizedField:
    return NormalizedField(
        name=name,
        path=name,
        nullable=nullable,
        position=position,
        type_mapping=TypeMapping(data_type_code=code, type_params=params or {}),
    )


def _nd(
    name: str = "public.users", fields: list[NormalizedField] | None = None
) -> NormalizedDataset:
    parts = name.split(".")
    schema_name = parts[0]
    table_name = parts[1] if len(parts) > 1 else name
    return NormalizedDataset(
        object_name=name,
        catalog_name="main",
        schema_name=schema_name,
        table_name=table_name,
        is_view=False,
        pk_columns=["id"],
        uq_constraints=[],
        comment=None,
        fields=fields or [_nf("id")],
        indexes=[],
        foreign_keys=[],
    )


class _Cache(TypeCache):
    def __init__(self, codes: list[str]):
        super().__init__(flavor_code="postgres14")
        self._by_code = {c: uuid.uuid4() for c in codes}


SYSTEM_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_dataset_happy_path():
    """No existing state — all creates should fire once per column."""
    fields = [_nf("id", position=0), _nf("email", position=1), _nf("name", position=2)]
    nd = _nd(fields=fields)
    client = _mock_client()
    cache = _Cache(["bigint"])

    results = await apply_new_datasets(
        client,
        system_id=SYSTEM_ID,
        datasets=[nd],
        type_cache=cache,
    )

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, AppliedDataset)
    assert r.object_name == "public.users"
    assert r.fields_count == 3

    client.datasets.create.assert_called_once()
    client.dataset_schemas.create.assert_called_once()
    assert client.fields.create.call_count == 3
    assert client.type_instances.create.call_count == 3
    assert client.field_bindings.create.call_count == 3
    # No schema list result → list was called but returned empty, so create was used
    client.dataset_schemas.list.assert_called_once()


@pytest.mark.asyncio
async def test_full_rerun_all_exists():
    """Existing dataset, schema, fields and bindings — zero creates."""
    existing_ds_id = uuid.uuid4()
    existing_schema_id = uuid.uuid4()
    field_ids = [uuid.uuid4(), uuid.uuid4()]
    fields_map = {"id": field_ids[0], "email": field_ids[1]}
    existing_schema = _obj(id=existing_schema_id, version_num=1)

    client = _mock_client(
        fields_map=fields_map,
        schemas=[existing_schema],
        bindings_field_ids=field_ids,
    )
    cache = _Cache(["bigint"])
    fields = [_nf("id", position=0), _nf("email", position=1)]
    nd = _nd(fields=fields)

    results = await apply_new_datasets(
        client,
        system_id=SYSTEM_ID,
        datasets=[nd],
        type_cache=cache,
        existing_dataset_ids={"public.users": existing_ds_id},
    )

    assert len(results) == 1
    r = results[0]
    assert r.dataset_id == existing_ds_id
    assert r.dataset_schema_id == existing_schema_id
    assert r.fields_count == 2

    client.datasets.create.assert_not_called()
    client.dataset_schemas.create.assert_not_called()
    client.fields.create.assert_not_called()
    client.type_instances.create.assert_not_called()
    client.field_bindings.create.assert_not_called()


@pytest.mark.asyncio
async def test_partial_rerun_bindings_missing():
    """Dataset, schema, and fields exist but bindings are absent — only type_instances and field_bindings created."""
    existing_ds_id = uuid.uuid4()
    existing_schema_id = uuid.uuid4()
    field_ids = [uuid.uuid4(), uuid.uuid4()]
    fields_map = {"id": field_ids[0], "email": field_ids[1]}
    existing_schema = _obj(id=existing_schema_id, version_num=1)

    client = _mock_client(
        fields_map=fields_map,
        schemas=[existing_schema],
        bindings_field_ids=[],  # no bindings yet
    )
    cache = _Cache(["bigint"])
    fields = [_nf("id", position=0), _nf("email", position=1)]
    nd = _nd(fields=fields)

    results = await apply_new_datasets(
        client,
        system_id=SYSTEM_ID,
        datasets=[nd],
        type_cache=cache,
        existing_dataset_ids={"public.users": existing_ds_id},
    )

    assert len(results) == 1
    r = results[0]
    assert r.fields_count == 2

    client.datasets.create.assert_not_called()
    client.dataset_schemas.create.assert_not_called()
    client.fields.create.assert_not_called()
    assert client.type_instances.create.call_count == 2
    assert client.field_bindings.create.call_count == 2


@pytest.mark.asyncio
async def test_partial_rerun_half_fields():
    """Dataset exists, half fields already present, schema absent — missing fields created and all N bindings created."""
    existing_ds_id = uuid.uuid4()
    existing_field_id = uuid.uuid4()
    fields_map = {"id": existing_field_id}  # only "id" exists, "email" missing

    client = _mock_client(
        fields_map=fields_map,
        schemas=[],  # no schema yet
        bindings_field_ids=[],
    )
    cache = _Cache(["bigint"])
    fields = [_nf("id", position=0), _nf("email", position=1)]
    nd = _nd(fields=fields)

    results = await apply_new_datasets(
        client,
        system_id=SYSTEM_ID,
        datasets=[nd],
        type_cache=cache,
        existing_dataset_ids={"public.users": existing_ds_id},
    )

    assert len(results) == 1
    r = results[0]
    assert r.fields_count == 2

    client.datasets.create.assert_not_called()
    # schema was absent → one create
    client.dataset_schemas.create.assert_called_once()
    # only "email" field is new
    assert client.fields.create.call_count == 1
    created_field_arg = client.fields.create.call_args[0][0]
    assert created_field_arg.name == "email"
    # all 2 bindings created (none were present)
    assert client.type_instances.create.call_count == 2
    assert client.field_bindings.create.call_count == 2
