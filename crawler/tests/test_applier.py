from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from aide_crawler.applier import AppliedDataset, apply_new_datasets
from aide_crawler.normalizer import NormalizedDataset, NormalizedField
from aide_crawler.type_cache import TypeCache
from aide_crawler.type_map import TypeChild, TypeNode

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
    c.fields.create_many = AsyncMock(
        side_effect=lambda items: [_obj(id=uuid.uuid4(), name=p.name) for p in items]
    )

    c.type_instances = AsyncMock()
    c.type_instances.create = AsyncMock(side_effect=lambda _p: _obj(id=uuid.uuid4()))
    c.type_instances.create_many = AsyncMock(
        side_effect=lambda items: [_obj(id=uuid.uuid4()) for _ in items]
    )

    c.field_bindings = AsyncMock()
    c.field_bindings.list = AsyncMock(
        return_value=_page([_obj(field_id=fid) for fid in (bindings_field_ids or [])])
    )
    c.field_bindings.create = AsyncMock(side_effect=lambda _p: _obj(id=uuid.uuid4()))
    c.field_bindings.create_many = AsyncMock(
        side_effect=lambda items: [_obj(id=uuid.uuid4()) for _ in items]
    )

    return c


def _nf(
    name: str,
    code: str = "bigint",
    position: int = 0,
    nullable: bool = False,
    params: dict | None = None,
    children: list[TypeChild] | None = None,
) -> NormalizedField:
    return NormalizedField(
        name=name,
        path=name,
        nullable=nullable,
        position=position,
        type_node=TypeNode(
            data_type_code=code,
            type_params=params or {},
            children=children or [],
        ),
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
    # All 3 missing fields created via a single batch call
    client.fields.create_many.assert_awaited_once()
    batch_items = client.fields.create_many.await_args[0][0]
    assert len(batch_items) == 3
    client.fields.create.assert_not_awaited()
    # All 3 fields are flat (bigint, depth=0 only) → one create_many call with 3 items.
    client.type_instances.create_many.assert_awaited_once()
    ti_batch_items = client.type_instances.create_many.await_args[0][0]
    assert len(ti_batch_items) == 3
    client.type_instances.create.assert_not_awaited()
    # All 3 bindings created via a single batch call
    client.field_bindings.create_many.assert_awaited_once()
    fb_batch_items = client.field_bindings.create_many.await_args[0][0]
    assert len(fb_batch_items) == 3
    client.field_bindings.create.assert_not_awaited()
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
    client.type_instances.create_many.assert_not_called()
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
    # 2 flat fields (bigint, depth=0 only) → one create_many call with 2 items.
    client.type_instances.create_many.assert_awaited_once()
    ti_batch_items = client.type_instances.create_many.await_args[0][0]
    assert len(ti_batch_items) == 2
    client.type_instances.create.assert_not_called()
    # 2 bindings created via a single batch call
    client.field_bindings.create_many.assert_awaited_once()
    fb_batch_items = client.field_bindings.create_many.await_args[0][0]
    assert len(fb_batch_items) == 2
    client.field_bindings.create.assert_not_called()


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
    # only "email" field is new — created via single batch call
    client.fields.create_many.assert_awaited_once()
    batch_items = client.fields.create_many.await_args[0][0]
    assert len(batch_items) == 1
    assert batch_items[0].name == "email"
    client.fields.create.assert_not_awaited()
    # all 2 bindings created (none were present); flat bigint fields → one create_many call.
    client.type_instances.create_many.assert_awaited_once()
    ti_batch_items = client.type_instances.create_many.await_args[0][0]
    assert len(ti_batch_items) == 2
    client.type_instances.create.assert_not_awaited()
    # 2 bindings created via a single batch call
    client.field_bindings.create_many.assert_awaited_once()
    fb_batch_items = client.field_bindings.create_many.await_args[0][0]
    assert len(fb_batch_items) == 2
    client.field_bindings.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_array_field_creates_two_type_instances_with_parent_link():
    """Array column → root TI for 'array' + child TI for element type with slot='item'.

    After the batch refactor, type instances are created via create_many:
    - depth-0 call: 1 item (array root, parent_id=None, slot=None)
    - depth-1 call: 1 item (text child, parent_id=<root id>, slot='item')
    """
    array_field = _nf(
        "tags",
        code="array",
        position=0,
        children=[
            TypeChild(
                slot="item", node=TypeNode(data_type_code="text", type_params={})
            ),
        ],
    )
    nd = _nd(fields=[array_field])
    cache = _Cache(["array", "text"])
    array_dt_id = cache._by_code["array"]
    text_dt_id = cache._by_code["text"]

    root_id = uuid.uuid4()
    child_id = uuid.uuid4()
    call_counter = [0]

    async def _ti_create_many(items):
        # First call: depth 0 (root); second call: depth 1 (child).
        if call_counter[0] == 0:
            call_counter[0] += 1
            return [_obj(id=root_id) for _ in items]
        call_counter[0] += 1
        return [_obj(id=child_id) for _ in items]

    client = _mock_client()
    client.type_instances.create_many = AsyncMock(side_effect=_ti_create_many)

    await apply_new_datasets(
        client, system_id=SYSTEM_ID, datasets=[nd], type_cache=cache
    )

    # Two create_many calls: one per depth level.
    assert client.type_instances.create_many.await_count == 2
    client.type_instances.create.assert_not_awaited()

    depth0_call = client.type_instances.create_many.await_args_list[0]
    depth1_call = client.type_instances.create_many.await_args_list[1]

    depth0_items = depth0_call.args[0]
    depth1_items = depth1_call.args[0]

    assert len(depth0_items) == 1
    assert depth0_items[0].data_type_id == array_dt_id
    assert depth0_items[0].parent_id is None
    assert depth0_items[0].slot is None

    assert len(depth1_items) == 1
    assert depth1_items[0].data_type_id == text_dt_id
    assert depth1_items[0].parent_id == root_id
    assert depth1_items[0].slot == "item"

    client.field_bindings.create_many.assert_awaited_once()
    fb_items = client.field_bindings.create_many.await_args[0][0]
    assert len(fb_items) == 1
    assert fb_items[0].type_instance_id == root_id


@pytest.mark.asyncio
async def test_applier_batches_missing_fields():
    """All missing fields in one dataset are created via a single create_many call."""
    client = _mock_client()

    dataset = _nd(
        name="public.users",
        fields=[_nf("col_a"), _nf("col_b"), _nf("col_c")],
    )
    cache = _Cache(["bigint"])

    await apply_new_datasets(
        client,
        system_id=SYSTEM_ID,
        datasets=[dataset],
        type_cache=cache,
    )

    # Batch fields called exactly once with all 3 missing fields
    client.fields.create_many.assert_awaited_once()
    batch_args = client.fields.create_many.await_args
    args, kwargs = batch_args
    items = args[0] if args else kwargs.get("items")
    assert len(items) == 3
    assert [i.name for i in items] == ["col_a", "col_b", "col_c"]

    # Per-item create NOT called (for fields specifically)
    client.fields.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_applier_batches_type_instances_by_depth():
    """Type instance creation issues one batch call per depth level across all fields."""
    client = _mock_client()

    # type_instances.create_many: simulate per-depth batch returning objects w/ ids.
    async def _ti_create_many(items):
        return [_obj(id=uuid.uuid4()) for _ in items]

    client.type_instances.create_many = AsyncMock(side_effect=_ti_create_many)

    cache = _Cache(["array", "bigint"])

    # Construct 3 fields, each with a 2-deep tree (array<bigint>).
    def _array_bigint_field(name: str, pos: int) -> NormalizedField:
        item = TypeNode(data_type_code="bigint", type_params={})
        root = TypeNode(
            data_type_code="array",
            type_params={},
            children=[TypeChild(slot="item", node=item)],
        )
        nf = _nf(name=name, code="array", position=pos)
        nf.type_node = root  # overwrite helper's default
        return nf

    fields = [
        _array_bigint_field("c_a", 0),
        _array_bigint_field("c_b", 1),
        _array_bigint_field("c_c", 2),
    ]
    dataset = _nd(name="public.users", fields=fields)

    await apply_new_datasets(
        client,
        system_id=SYSTEM_ID,
        datasets=[dataset],
        type_cache=cache,
    )

    # Two batch calls: depth 0 (3 roots), depth 1 (3 children).
    assert client.type_instances.create_many.await_count == 2
    call0 = client.type_instances.create_many.await_args_list[0]
    call1 = client.type_instances.create_many.await_args_list[1]

    depth0_items = call0.args[0]
    depth1_items = call1.args[0]
    assert len(depth0_items) == 3
    assert len(depth1_items) == 3
    assert all(i.parent_id is None for i in depth0_items)
    assert all(i.parent_id is not None for i in depth1_items)

    # Per-item create NOT called for type_instances.
    assert client.type_instances.create.await_count == 0


@pytest.mark.asyncio
async def test_applier_batches_bindings():
    """Field bindings are created via a single create_many call per dataset."""
    client = _mock_client()

    async def _fields_create_many(items):
        return [_obj(id=uuid.uuid4(), name=p.name) for p in items]

    client.fields.create_many = AsyncMock(side_effect=_fields_create_many)

    async def _ti_create_many(items):
        return [_obj(id=uuid.uuid4()) for _ in items]

    client.type_instances.create_many = AsyncMock(side_effect=_ti_create_many)

    async def _fb_create_many(items):
        return [_obj(id=uuid.uuid4()) for _ in items]

    client.field_bindings.create_many = AsyncMock(side_effect=_fb_create_many)

    cache = _Cache(["bigint"])

    dataset = _nd(
        name="public.users",
        fields=[_nf("c_a"), _nf("c_b"), _nf("c_c"), _nf("c_d")],
    )

    await apply_new_datasets(
        client,
        system_id=uuid.uuid4(),
        datasets=[dataset],
        type_cache=cache,
    )

    client.field_bindings.create_many.assert_awaited_once()
    call = client.field_bindings.create_many.await_args
    args, kwargs = call
    items = args[0] if args else kwargs.get("items")
    assert len(items) == 4
    # Order matches input field order
    assert [i.position for i in items] == [0, 0, 0, 0]  # _nf default position
    # Per-item create NOT called
    client.field_bindings.create.assert_not_awaited()


# ---------------------------------------------------------------------------
# apply_versioned_datasets
# ---------------------------------------------------------------------------


def _snapshot(field_id: uuid.UUID, ti_id: uuid.UUID):
    """Build a FieldBindingSnapshot for test fixtures."""
    from aide_crawler.differ import FieldBindingSnapshot

    return FieldBindingSnapshot(field_id=field_id, type_instance_id=ti_id)


def _plan(
    *,
    dataset_id: uuid.UUID,
    object_name: str = "public.orders",
    current_version_num: int = 1,
    next_version_num: int = 2,
    all_fields: list,
    unchanged: dict | None = None,
    added: list | None = None,
    type_changed: list | None = None,
    removed_ids: list | None = None,
):
    from aide_crawler.differ import VersionedDatasetPlan

    return VersionedDatasetPlan(
        dataset_id=dataset_id,
        object_name=object_name,
        current_version_num=current_version_num,
        next_version_num=next_version_num,
        all_fields=all_fields,
        unchanged_field_bindings=unchanged or {},
        added_fields=added or [],
        type_changed_fields=type_changed or [],
        removed_field_ids=removed_ids or [],
    )


@pytest.mark.asyncio
async def test_versioned_apply_posts_schema_with_next_version_num():
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    fields = [_nf("id", position=0)]
    plan = _plan(
        dataset_id=ds_id,
        current_version_num=1,
        next_version_num=2,
        all_fields=fields,
        unchanged={"id": _snapshot(keep_id, keep_ti)},
    )
    client = _mock_client()
    cache = _Cache(["bigint"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    client.dataset_schemas.create.assert_awaited_once()
    created_arg = client.dataset_schemas.create.await_args.args[0]
    assert created_arg.dataset_id == ds_id
    assert created_arg.version_num == 2


@pytest.mark.asyncio
async def test_versioned_apply_allocates_version_skipping_orphans():
    """next_version_num=3 (baseline v1, orphan v2) → POSTs v3, not v2."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    fields = [_nf("id", position=0)]
    plan = _plan(
        dataset_id=ds_id,
        current_version_num=1,
        next_version_num=3,
        all_fields=fields,
        unchanged={"id": _snapshot(keep_id, keep_ti)},
    )
    client = _mock_client()
    cache = _Cache(["bigint"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    created_arg = client.dataset_schemas.create.await_args.args[0]
    assert created_arg.version_num == 3


@pytest.mark.asyncio
async def test_versioned_apply_reuses_unchanged_type_instance():
    """Unchanged fields → binding cites existing type_instance_id; no new TI posts."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    id_field = uuid.uuid4()
    total_field = uuid.uuid4()
    id_ti = uuid.uuid4()
    total_ti = uuid.uuid4()
    schema_id = uuid.uuid4()
    fields = [_nf("id", position=0), _nf("total", position=1)]
    plan = _plan(
        dataset_id=ds_id,
        all_fields=fields,
        unchanged={
            "id": _snapshot(id_field, id_ti),
            "total": _snapshot(total_field, total_ti),
        },
    )

    client = _mock_client()
    client.dataset_schemas.create = AsyncMock(return_value=_obj(id=schema_id))
    cache = _Cache(["bigint"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    # No TypeInstance creation — nothing changed.
    client.type_instances.create_many.assert_not_called()
    client.type_instances.create.assert_not_called()
    # No field creation — nothing added.
    client.fields.create_many.assert_not_called()
    # One binding batch with both fields pointing at existing TIs.
    client.field_bindings.create_many.assert_awaited_once()
    items = client.field_bindings.create_many.await_args.args[0]
    assert len(items) == 2
    by_field = {i.field_id: i for i in items}
    assert by_field[id_field].type_instance_id == id_ti
    assert by_field[id_field].dataset_schema_id == schema_id
    assert by_field[id_field].position == 0
    assert by_field[total_field].type_instance_id == total_ti
    assert by_field[total_field].position == 1


@pytest.mark.asyncio
async def test_versioned_apply_creates_fields_and_trees_for_added():
    """Added field → fields.create_many called; TI batch creates a new tree."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    schema_id = uuid.uuid4()
    new_field_id = uuid.uuid4()
    new_ti_id = uuid.uuid4()

    all_fields = [_nf("id", position=0), _nf("email", code="text", position=1)]
    added = [_nf("email", code="text", position=1)]
    plan = _plan(
        dataset_id=ds_id,
        all_fields=all_fields,
        unchanged={"id": _snapshot(keep_id, keep_ti)},
        added=added,
    )

    client = _mock_client()
    client.dataset_schemas.create = AsyncMock(return_value=_obj(id=schema_id))
    client.fields.create_many = AsyncMock(
        return_value=[_obj(id=new_field_id, name="email")]
    )
    client.type_instances.create_many = AsyncMock(return_value=[_obj(id=new_ti_id)])
    cache = _Cache(["bigint", "text"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    # Field create_many called once with exactly one added field
    client.fields.create_many.assert_awaited_once()
    created_fields_arg = client.fields.create_many.await_args.args[0]
    assert len(created_fields_arg) == 1
    assert created_fields_arg[0].name == "email"
    assert created_fields_arg[0].dataset_id == ds_id

    # Type instance batch called; depth 0 only for a flat "text" node
    assert client.type_instances.create_many.await_count == 1

    # Bindings batch has 2 entries; email points to new TI
    client.field_bindings.create_many.assert_awaited_once()
    items = client.field_bindings.create_many.await_args.args[0]
    by_field = {i.field_id: i for i in items}
    assert by_field[keep_id].type_instance_id == keep_ti
    assert by_field[new_field_id].type_instance_id == new_ti_id
    assert by_field[new_field_id].position == 1


@pytest.mark.asyncio
async def test_versioned_apply_rebuilds_tree_for_type_changes():
    """Type-changed field → new TypeInstance; binding uses new TI (not old)."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    field_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    new_ti_id = uuid.uuid4()

    changed_nf = _nf("n", code="bigint", position=0)
    plan = _plan(
        dataset_id=ds_id,
        all_fields=[changed_nf],
        unchanged={},
        type_changed=[changed_nf],
    )
    # Feed in the pre-existing field_id via a helper: the plan's type_changed
    # field references the same NormalizedField, but the applier must know
    # the Field row already exists. We convey this via a small extension:
    # type_changed fields' existing field_ids come from a separate dict on
    # the plan. The applier fetches {name: field_id} for the dataset.
    client = _mock_client(fields_map={"n": field_id})
    client.dataset_schemas.create = AsyncMock(return_value=_obj(id=schema_id))
    client.type_instances.create_many = AsyncMock(return_value=[_obj(id=new_ti_id)])
    cache = _Cache(["bigint"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    # No new Field row for a type-changed column.
    client.fields.create_many.assert_not_called()
    # One TI batch call for the one type-changed field.
    assert client.type_instances.create_many.await_count == 1
    # Binding points to the new TI.
    client.field_bindings.create_many.assert_awaited_once()
    items = client.field_bindings.create_many.await_args.args[0]
    assert len(items) == 1
    assert items[0].field_id == field_id
    assert items[0].type_instance_id == new_ti_id


@pytest.mark.asyncio
async def test_versioned_apply_omits_removed_fields():
    """removed_field_ids are not in the new binding set (no binding row for them)."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    drop_id = uuid.uuid4()
    schema_id = uuid.uuid4()

    plan = _plan(
        dataset_id=ds_id,
        all_fields=[_nf("id", position=0)],
        unchanged={"id": _snapshot(keep_id, keep_ti)},
        removed_ids=[drop_id],
    )
    client = _mock_client()
    client.dataset_schemas.create = AsyncMock(return_value=_obj(id=schema_id))
    cache = _Cache(["bigint"])

    await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    items = client.field_bindings.create_many.await_args.args[0]
    field_ids_in_bindings = {i.field_id for i in items}
    assert drop_id not in field_ids_in_bindings


@pytest.mark.asyncio
async def test_versioned_apply_409_reraises():
    """Unique (dataset_id, version_num) collision → exception propagates."""
    from aide_crawler.applier import apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    plan = _plan(
        dataset_id=ds_id,
        all_fields=[_nf("id", position=0)],
        unchanged={"id": _snapshot(keep_id, keep_ti)},
    )

    class _Conflict(Exception):
        pass

    client = _mock_client()
    client.dataset_schemas.create = AsyncMock(side_effect=_Conflict("409"))
    cache = _Cache(["bigint"])

    with pytest.raises(_Conflict):
        await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    # No downstream calls after schema POST failed
    client.fields.create_many.assert_not_called()
    client.type_instances.create_many.assert_not_called()
    client.field_bindings.create_many.assert_not_called()


@pytest.mark.asyncio
async def test_versioned_apply_returns_result_records():
    """Return value: one VersionedDataset per plan with the new schema id + version."""
    from aide_crawler.applier import VersionedDataset, apply_versioned_datasets

    ds_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    keep_ti = uuid.uuid4()
    new_schema_id = uuid.uuid4()

    plan = _plan(
        dataset_id=ds_id,
        object_name="public.orders",
        current_version_num=1,
        next_version_num=2,
        all_fields=[_nf("id", position=0)],
        unchanged={"id": _snapshot(keep_id, keep_ti)},
    )
    client = _mock_client()
    client.dataset_schemas.create = AsyncMock(return_value=_obj(id=new_schema_id))
    cache = _Cache(["bigint"])

    results = await apply_versioned_datasets(client, plans=[plan], type_cache=cache)

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, VersionedDataset)
    assert r.dataset_id == ds_id
    assert r.object_name == "public.orders"
    assert r.old_version_num == 1
    assert r.new_version_num == 2
    assert r.dataset_schema_id == new_schema_id
    assert r.fields_added == 0
    assert r.fields_removed == 0
    assert r.type_changes == 0
