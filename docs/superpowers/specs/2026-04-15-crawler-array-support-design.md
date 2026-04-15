# Crawler Type Coverage Expansion (ARRAY + PG14 gaps) — Design

**Date:** 2026-04-15
**Status:** Approved

## Problem

`crawler/aide_crawler/type_map.py::resolve_type` currently maps a small subset of `backend/scripts/data/postgres14.yaml` types. Concrete gaps:

1. **ARRAY** — not handled at all. Any `text[]` column raises `UnknownTypeError`. The metastore data model already supports compound types via `TypeInstance.parent_id` + `TypeInstance.slot`; the crawler just doesn't use it.
2. **timezone-aware time/timestamp** — `TIME(timezone=True)` and `TIMESTAMP(timezone=True)` collapse to plain `time`/`timestamp`, losing tz.
3. **CHAR** — falls into the `String → varchar` branch.
4. Several PG-dialect types are missing entirely: `xml, money, macaddr8, tsquery, bit, varbit, oid, int4range, int8range, numrange, tsrange, tstzrange, daterange`.
5. **`UnknownTypeError`** prints only the SA class name, hiding the original PG type — painful for users hitting unsupported geometric/system types.

## Goal

- ARRAY produces an `array` parent + recursive child(ren) `TypeInstance` chain bound to the field.
- All YAML-declared PG types that have a corresponding SA class are mapped, with correct `type_params` (length, precision, scale) and tz disambiguation.
- Unmapped types fail with a message that names the original SQL type.

## Approach

Introduce a tree representation of types and propagate it through map → normalize → apply. Extend `type_map.py` to cover the full SA-reachable subset of PG14 types.

### 1. `type_map.py` — `TypeNode` tree + extended PG coverage

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

- **ARRAY first**: if `isinstance(sa_type, sa_types.ARRAY)`, return
  ```
  TypeNode(
      data_type_code="array",
      type_params={},
      children=[TypeChild(slot="item", node=resolve_type(dialect_name, sa_type.item_type))],
  )
  ```
  Recursive — `ARRAY(ARRAY(...))` produces an N-level tree.
- **Timezone-aware special-case** (PG only): if `isinstance(sa_type, (sa_types.TIME, sa_types.DateTime))` and `getattr(sa_type, "timezone", False)`, map to `timetz` / `timestamptz` respectively.
- **DIALECT_TYPE_MAP** lookup by `(dialect_name, type(sa_type).__name__)`.
- **GENERIC_TYPE_MAP** lookup by isinstance.
- Unknown → `UnknownTypeError(dialect_name, sa_type)` carrying `repr(sa_type)`.

`slot` constant for an array element: `"item"`.

#### Extended `DIALECT_TYPE_MAP` (PostgreSQL)

Existing: `JSONB, JSON, UUID, INET, CIDR, MACADDR, INTERVAL, TSVECTOR, BYTEA, ENUM`.

Add:
- `XML → xml`
- `MONEY → money`
- `MACADDR8 → macaddr8`
- `TSQUERY → tsquery`
- `OID → oid`
- `INT4RANGE → int4range`, `INT8RANGE → int8range`, `NUMRANGE → numrange`, `TSRANGE → tsrange`, `TSTZRANGE → tstzrange`, `DATERANGE → daterange`

`BIT` needs branching on `.varying` (PG dialect `BIT(varying=True)` represents `bit varying`):
- not in `DIALECT_TYPE_MAP`; handled in `resolve_type`: `isinstance(sa_type, pg.BIT)` → `varbit` if `sa_type.varying` else `bit`.

#### Extended `GENERIC_TYPE_MAP`

Insert `(sa_types.CHAR, "char")` **before** the `String` row. Order matters because `CHAR` is a subclass of `String` in SA.

#### `_extract_params`

Already covers `length, precision, scale`. Add nothing — `BIT.length` reuses the existing branch.

#### `UnknownTypeError`

Change signature from `(dialect_name, cls_name)` to `(dialect_name, sa_type)`; format message as `f"Unknown {dialect_name} type: {sa_type!r}"`. Update the single raise site.

#### Out of mapping (no SA class, document only)

`point, line, lseg, box, path, polygon, circle, pg_lsn, txid_snapshot` — SA Inspector returns `NullType`. Surfaced as `UnknownTypeError` with the readable repr. Future work: pull names from `pg_catalog.pg_type`.

`smallserial, serial, bigserial` — indistinguishable from `smallint/integer/bigint` via SA Inspector (sequence default lives in `default`). Mapped to the integer family. Distinguishing them is a separate feature (default introspection).

### 2. `normalizer.py`

`NormalizedField.type_mapping: TypeMapping` → `NormalizedField.type_node: TypeNode`. No other changes — normalizer just forwards what `resolve_type` returns.

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

Unchanged. The applier already skips creating a new `TypeInstance` if a `FieldBinding` for that field already exists in the schema. Re-runs against an unchanged target produce no new TI trees. Schema evolution (column type change) is out of scope — owned by the diff layer.

## Testing

- `crawler/tests/test_type_map.py`
  - Leaf primitives (one assertion per new mapping): `XML, MONEY, MACADDR8, TSQUERY, OID, INT4RANGE, INT8RANGE, NUMRANGE, TSRANGE, TSTZRANGE, DATERANGE` → expected code, empty params.
  - `CHAR(5)` → `code="char", params={"length": 5}` (must NOT match `varchar`).
  - `BIT(8)` → `code="bit", params={"length": 8}`; `BIT(8, varying=True)` → `code="varbit", params={"length": 8}`.
  - `TIME()` → `time`; `TIME(timezone=True)` → `timetz`. `DateTime()` → `timestamp`; `DateTime(timezone=True)` → `timestamptz`. With `precision=3` → params carry it.
  - ARRAY: `ARRAY(Integer())` → root `array`, one child `slot="item"` code=`integer`. `ARRAY(ARRAY(Text()))` → 3-level tree. `ARRAY(String(64))` → child `varchar` with `length=64`.
  - Unknown leaf raises `UnknownTypeError`; message contains `repr(sa_type)`.
- `crawler/tests/test_normalizer.py`
  - Update existing assertions from `type_mapping` → `type_node`.
  - Add a fixture column with `ARRAY(Integer())` and assert tree structure.
- `crawler/tests/test_applier.py` (mocked SDK client)
  - Array field → exactly 2 `type_instances.create` calls.
    - First call: `parent_id=None`, `slot=None`, `data_type_id=<array>`.
    - Second call: `parent_id=<first.id>`, `slot="item"`, `data_type_id=<integer>`.
  - Resulting `FieldBindingCreate.type_instance_id` is the root id.
- Manual regression via `scripts/manual_test/seed_target.sh` (already seeds `text[]` and `integer[]`). Add a few extra columns to that seed: `numrange`, `xml`, `bit(8)`, `timestamptz`, `char(5)` so the manual run exercises the new mappings.

## Out of Scope

- MySQL and other dialects.
- PostgreSQL composite (ROW) types — the tree machinery accepts them, but registering user-defined types as `data_types` is a separate design.
- Geometric and system types (`point, line, lseg, box, path, polygon, circle, pg_lsn, txid_snapshot`) — no SA classes; would require querying `pg_catalog` directly.
- `smallserial/serial/bigserial` distinction — needs default-string introspection.
- Updating an existing TI tree when a column's type changes — owned by the diff layer.

## Files Touched

- Modify: `crawler/aide_crawler/type_map.py`
- Modify: `crawler/aide_crawler/errors.py` (`UnknownTypeError` signature/message)
- Modify: `crawler/aide_crawler/normalizer.py`
- Modify: `crawler/aide_crawler/applier.py`
- Modify/Create: `crawler/tests/test_type_map.py`
- Modify: `crawler/tests/test_normalizer.py`
- Modify/Create: `crawler/tests/test_applier.py`
- Modify: `scripts/manual_test/seed_target.sh` (extra type columns for manual regression)
