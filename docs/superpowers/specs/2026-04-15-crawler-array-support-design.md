# Crawler ARRAY Type Support — Design

**Date:** 2026-04-15
**Status:** Approved

## Problem

`crawler/aide_crawler/type_map.py::resolve_type` returns a flat `TypeMapping(code, params)`. PostgreSQL `ARRAY` is not handled: any column like `text[]` raises `UnknownTypeError` mid-crawl. Yet the metastore data model already supports compound types via `TypeInstance.parent_id` + `TypeInstance.slot`, and `data_types` already contains the `array` row (see `backend/scripts/data/postgres14.yaml:149`). The crawler simply doesn't use the composition.

## Goal

Crawler reads array columns from PostgreSQL, resolves their element type, and writes a parent (`array`) + child (`<element>`) `TypeInstance` chain bound to the field. Recursive: arrays of arrays produce N-level chains.

## Approach

Introduce a tree representation of types and propagate it through map → normalize → apply.

### 1. `type_map.py` — `TypeNode` tree

Replace `TypeMapping` with:

```python
@dataclass
class TypeNode:
    data_type_code: str
    type_params: dict[str, Any]
    children: list["TypeChild"] = field(default_factory=list)

@dataclass
class TypeChild:
    slot: str
    node: TypeNode
```

`resolve_type(dialect_name, sa_type) -> TypeNode`:

- If `isinstance(sa_type, sa_types.ARRAY)`: return
  ```
  TypeNode(
      data_type_code="array",
      type_params={},
      children=[TypeChild(slot="item", node=resolve_type(dialect_name, sa_type.item_type))],
  )
  ```
- Otherwise: same `DIALECT_TYPE_MAP` / `GENERIC_TYPE_MAP` lookup as today, returning a leaf `TypeNode` with empty `children`.
- Unknown leaf → `UnknownTypeError` (unchanged).

The `slot` constant for an array's single element is `"item"`.

### 2. `normalizer.py`

`NormalizedField.type_mapping: TypeMapping` becomes `NormalizedField.type_node: TypeNode`. No other changes — normalizer just forwards what `resolve_type` returns.

### 3. `applier.py` — recursive TypeInstance creation

Add helper:

```python
async def _create_type_instance_tree(
    client,
    *,
    node: TypeNode,
    type_cache: TypeCache,
    parent_id: uuid.UUID | None = None,
    slot: str | None = None,
) -> uuid.UUID:
    data_type_id = type_cache.resolve(node.data_type_code)
    ti = await client.type_instances.create(
        TypeInstanceCreate(
            data_type_id=data_type_id,
            type_params=node.type_params or None,
            parent_id=parent_id,
            slot=slot,
        )
    )
    for child in node.children:
        await _create_type_instance_tree(
            client,
            node=child.node,
            type_cache=type_cache,
            parent_id=ti.id,
            slot=child.slot,
        )
    return ti.id
```

In `apply_new_datasets`, replace the current single `client.type_instances.create(...)` call with `ti_id = await _create_type_instance_tree(...)`, and pass `type_instance_id=ti_id` into `FieldBindingCreate` exactly as today.

### Idempotency

Unchanged. The applier already skips creating a new `TypeInstance` if a `FieldBinding` for that field already exists in the schema. Re-runs against an unchanged target produce no new TI trees. Schema evolution (column type change) is out of scope for this work — diff layer handles it separately.

## Testing

- `crawler/tests/test_type_map.py`
  - leaf: `Integer()` → `TypeNode(code="integer", children=[])`
  - one-dim: `ARRAY(Integer())` → root `array`, one child `slot="item"` code=`integer`
  - nested: `ARRAY(ARRAY(Text()))` → 3-level tree
  - params on element: `ARRAY(String(64))` → child has `type_params={"length": 64}`
  - unknown leaf still raises `UnknownTypeError`
- `crawler/tests/test_normalizer.py`
  - update existing assertions from `type_mapping` → `type_node`
  - add a fixture column with `ARRAY(Integer())` and assert tree structure
- `crawler/tests/test_applier.py` (mocked SDK client)
  - array field → exactly 2 `type_instances.create` calls
  - first call: `parent_id=None`, `slot=None`, `data_type_id=<array>`
  - second call: `parent_id=<first.id>`, `slot="item"`, `data_type_id=<integer>`
  - resulting `FieldBindingCreate.type_instance_id` is the root id
- Manual regression via existing `scripts/manual_test/seed_target.sh` (already seeds `text[]` and `integer[]`).

## Out of Scope

- MySQL and other dialects (no native array type).
- PostgreSQL composite (ROW) types — the same tree machinery will accept them later with `slot=<column_name>`, no design change needed.
- Updating an existing TI tree when a column's type changes — owned by the diff/apply-changes layer, not this work.

## Files Touched

- Modify: `crawler/aide_crawler/type_map.py`
- Modify: `crawler/aide_crawler/normalizer.py`
- Modify: `crawler/aide_crawler/applier.py`
- Modify/Create: `crawler/tests/test_type_map.py`
- Modify: `crawler/tests/test_normalizer.py`
- Modify/Create: `crawler/tests/test_applier.py`
