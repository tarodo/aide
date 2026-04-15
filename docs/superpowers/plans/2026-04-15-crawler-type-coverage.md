# Crawler Type Coverage Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crawler resolves PostgreSQL ARRAY columns into recursive `TypeInstance` trees and maps every `postgres14.yaml` type that has a corresponding SQLAlchemy class.

**Architecture:** Replace flat `TypeMapping` with a recursive `TypeNode` tree. `type_map.resolve_type` becomes recursive, special-cases ARRAY and timezone-aware temporal types, adds missing PG-dialect mappings, and improves the error message. `normalizer.NormalizedField` carries `type_node` (renamed from `type_mapping`). `applier` walks the tree to create parent + child `TypeInstance` rows linked via `parent_id`/`slot`.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 (sync Inspector + `sqlalchemy.dialects.postgresql`), `pytest`, `pytest-asyncio`. Tests run from `crawler/` via `cd crawler && uv run pytest tests/`.

---

## Reference: target types

`backend/scripts/data/postgres14.yaml` defines 47 codes. Mappings to add or fix in this plan:

| Code | SA class | Notes |
|------|----------|-------|
| `array` | `sqlalchemy.types.ARRAY` | recursive child via `slot="item"` |
| `char` | `sqlalchemy.types.CHAR` | must precede `String` in generic map |
| `timetz` | `sqlalchemy.types.TIME(timezone=True)` | special-case branch |
| `timestamptz` | `sqlalchemy.types.DateTime(timezone=True)` | special-case branch |
| `xml` | `sqlalchemy.dialects.postgresql.XML` | dialect map |
| `money` | `sqlalchemy.dialects.postgresql.MONEY` | dialect map |
| `macaddr8` | `sqlalchemy.dialects.postgresql.MACADDR8` | dialect map |
| `tsquery` | `sqlalchemy.dialects.postgresql.TSQUERY` | dialect map |
| `oid` | `sqlalchemy.dialects.postgresql.OID` | dialect map |
| `bit` | `sqlalchemy.dialects.postgresql.BIT(varying=False)` | branch on `.varying` |
| `varbit` | `sqlalchemy.dialects.postgresql.BIT(varying=True)` | branch on `.varying` |
| `int4range` | `sqlalchemy.dialects.postgresql.INT4RANGE` | dialect map |
| `int8range` | `sqlalchemy.dialects.postgresql.INT8RANGE` | dialect map |
| `numrange` | `sqlalchemy.dialects.postgresql.NUMRANGE` | dialect map |
| `tsrange` | `sqlalchemy.dialects.postgresql.TSRANGE` | dialect map |
| `tstzrange` | `sqlalchemy.dialects.postgresql.TSTZRANGE` | dialect map |
| `daterange` | `sqlalchemy.dialects.postgresql.DATERANGE` | dialect map |

Already mapped (no change): `bigint, smallint, integer, boolean, date, time, timestamp, double, real, numeric, bytea, text, varchar, uuid, json, jsonb, inet, cidr, macaddr, interval, tsvector, enum`.

Out of scope (no SA class): `point, line, lseg, box, path, polygon, circle, pg_lsn, txid_snapshot, smallserial, serial, bigserial, decimal` (alias of numeric).

---

## File Structure

- Modify: `crawler/aide_crawler/type_map.py` — `TypeNode`/`TypeChild` dataclasses replace `TypeMapping`; `resolve_type` becomes recursive with ARRAY + tz + extended PG mappings.
- Modify: `crawler/aide_crawler/errors.py` — `UnknownTypeError` accepts the SA type object and embeds `repr(sa_type)`.
- Modify: `crawler/aide_crawler/normalizer.py` — `NormalizedField.type_mapping` → `type_node`.
- Modify: `crawler/aide_crawler/applier.py` — recursive `_create_type_instance_tree` helper used in `apply_new_datasets`.
- Modify: `crawler/tests/test_type_map.py` — coverage for every new mapping plus ARRAY tree shapes.
- Modify: `crawler/tests/test_normalizer.py` — rename to `type_node`; add ARRAY column case.
- Modify: `crawler/tests/test_applier.py` — rename helper, add ARRAY tree creation test.
- Modify: `scripts/manual_test/seed_target.sh` — add columns covering new mappings for manual regression.

---

### Task 1: Refactor `UnknownTypeError` to carry the SA type

**Files:**
- Modify: `crawler/aide_crawler/errors.py`

- [ ] **Step 1: Replace the class**

```python
# crawler/aide_crawler/errors.py
from __future__ import annotations

from typing import Any


class CrawlerError(Exception):
    """Base class for crawler-specific errors."""


class UnknownTypeError(CrawlerError):
    def __init__(self, dialect: str, sa_type: Any):
        super().__init__(
            f"Unknown SQL type: dialect={dialect} sa_type={sa_type!r}"
        )
        self.dialect = dialect
        self.sa_type = sa_type
        self.sa_class_name = type(sa_type).__name__


class TypeNotInFlavorError(CrawlerError):
    def __init__(self, code: str, flavor_code: str | None = None):
        ctx = f" flavor={flavor_code}" if flavor_code else ""
        super().__init__(f"DataType code '{code}' not found in metastore{ctx}")
        self.code = code
        self.flavor_code = flavor_code
```

- [ ] **Step 2: Commit**

```bash
git add crawler/aide_crawler/errors.py
git commit -m "refactor(crawler): UnknownTypeError carries sa_type repr"
```

---

### Task 2: Failing tests for `TypeNode`, ARRAY, tz, and extended PG mappings

**Files:**
- Modify: `crawler/tests/test_type_map.py`

- [ ] **Step 1: Replace the test file with the expanded suite**

```python
# crawler/tests/test_type_map.py
import pytest
from sqlalchemy import types as sa_types
from sqlalchemy.dialects import postgresql as pg

from aide_crawler.errors import UnknownTypeError
from aide_crawler.type_map import TypeNode, resolve_type


@pytest.mark.parametrize(
    "sa_type,expected_code",
    [
        (sa_types.SmallInteger(), "smallint"),
        (sa_types.Integer(), "integer"),
        (sa_types.BigInteger(), "bigint"),
        (sa_types.Numeric(10, 2), "numeric"),
        (sa_types.Float(), "real"),
        (sa_types.Double(), "double"),
        (sa_types.String(50), "varchar"),
        (sa_types.Text(), "text"),
        (sa_types.Boolean(), "boolean"),
        (sa_types.Date(), "date"),
        (sa_types.Time(), "time"),
        (sa_types.DateTime(), "timestamp"),
        (sa_types.LargeBinary(), "bytea"),
        (sa_types.Uuid(), "uuid"),
        (sa_types.CHAR(5), "char"),
        (pg.JSONB(), "jsonb"),
        (pg.JSON(), "json"),
        (pg.INET(), "inet"),
        (pg.CIDR(), "cidr"),
        (pg.MACADDR(), "macaddr"),
        (pg.MACADDR8(), "macaddr8"),
        (pg.INTERVAL(), "interval"),
        (pg.TSVECTOR(), "tsvector"),
        (pg.TSQUERY(), "tsquery"),
        (pg.BYTEA(), "bytea"),
        (pg.XML(), "xml"),
        (pg.MONEY(), "money"),
        (pg.OID(), "oid"),
        (pg.INT4RANGE(), "int4range"),
        (pg.INT8RANGE(), "int8range"),
        (pg.NUMRANGE(), "numrange"),
        (pg.TSRANGE(), "tsrange"),
        (pg.TSTZRANGE(), "tstzrange"),
        (pg.DATERANGE(), "daterange"),
    ],
)
def test_resolve_known_leaf_types(sa_type, expected_code):
    node = resolve_type("postgresql", sa_type)
    assert isinstance(node, TypeNode)
    assert node.data_type_code == expected_code
    assert node.children == []


def test_numeric_params_extracted():
    node = resolve_type("postgresql", sa_types.Numeric(14, 4))
    assert node.type_params == {"precision": 14, "scale": 4}


def test_varchar_length_extracted():
    node = resolve_type("postgresql", sa_types.String(255))
    assert node.type_params == {"length": 255}


def test_char_distinguished_from_varchar():
    node = resolve_type("postgresql", sa_types.CHAR(10))
    assert node.data_type_code == "char"
    assert node.type_params == {"length": 10}


def test_text_has_no_params():
    node = resolve_type("postgresql", sa_types.Text())
    assert node.type_params == {}


def test_time_with_timezone_maps_to_timetz():
    plain = resolve_type("postgresql", sa_types.Time())
    tz = resolve_type("postgresql", sa_types.Time(timezone=True))
    assert plain.data_type_code == "time"
    assert tz.data_type_code == "timetz"


def test_timestamp_with_timezone_maps_to_timestamptz():
    plain = resolve_type("postgresql", sa_types.DateTime())
    tz = resolve_type("postgresql", sa_types.DateTime(timezone=True))
    assert plain.data_type_code == "timestamp"
    assert tz.data_type_code == "timestamptz"


def test_bit_fixed_vs_varying():
    fixed = resolve_type("postgresql", pg.BIT(8))
    varying = resolve_type("postgresql", pg.BIT(8, varying=True))
    assert fixed.data_type_code == "bit"
    assert fixed.type_params == {"length": 8}
    assert varying.data_type_code == "varbit"
    assert varying.type_params == {"length": 8}


def test_array_of_integer_builds_two_level_tree():
    node = resolve_type("postgresql", sa_types.ARRAY(sa_types.Integer()))
    assert node.data_type_code == "array"
    assert node.type_params == {}
    assert len(node.children) == 1
    child = node.children[0]
    assert child.slot == "item"
    assert child.node.data_type_code == "integer"
    assert child.node.children == []


def test_array_of_array_of_text_builds_three_level_tree():
    node = resolve_type(
        "postgresql", sa_types.ARRAY(sa_types.ARRAY(sa_types.Text()))
    )
    assert node.data_type_code == "array"
    inner = node.children[0].node
    assert inner.data_type_code == "array"
    leaf = inner.children[0].node
    assert leaf.data_type_code == "text"


def test_array_of_varchar_propagates_length_to_child():
    node = resolve_type("postgresql", sa_types.ARRAY(sa_types.String(64)))
    child = node.children[0].node
    assert child.data_type_code == "varchar"
    assert child.type_params == {"length": 64}


def test_unknown_type_raises_with_repr():
    class Mystery:
        def __repr__(self) -> str:
            return "Mystery()"

    with pytest.raises(UnknownTypeError) as exc:
        resolve_type("postgresql", Mystery())
    assert "Mystery()" in str(exc.value)
```

- [ ] **Step 2: Run the suite to confirm it fails**

```bash
cd crawler && uv run pytest tests/test_type_map.py -v
```

Expected: collection error (cannot import `TypeNode`) or assertion failures across the new cases.

---

### Task 3: Implement `TypeNode` tree, ARRAY recursion, and extended PG coverage

**Files:**
- Modify: `crawler/aide_crawler/type_map.py`

- [ ] **Step 1: Rewrite the module**

```python
# crawler/aide_crawler/type_map.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import types as sa_types
from sqlalchemy.dialects import postgresql as pg

from aide_crawler.errors import UnknownTypeError

ARRAY_ITEM_SLOT = "item"


@dataclass
class TypeNode:
    data_type_code: str
    type_params: dict[str, Any]
    children: list["TypeChild"] = field(default_factory=list)


@dataclass
class TypeChild:
    slot: str
    node: TypeNode


# Generic SA → postgres14 code map. Order matters: subclasses before parents.
GENERIC_TYPE_MAP: list[tuple[type, str]] = [
    (sa_types.BigInteger, "bigint"),
    (sa_types.SmallInteger, "smallint"),
    (sa_types.Integer, "integer"),
    (sa_types.Boolean, "boolean"),
    (sa_types.Date, "date"),
    (sa_types.Time, "time"),
    (sa_types.DateTime, "timestamp"),
    (sa_types.Double, "double"),
    (sa_types.Float, "real"),
    (sa_types.Numeric, "numeric"),
    (sa_types.LargeBinary, "bytea"),
    (sa_types.UnicodeText, "text"),
    (sa_types.Text, "text"),
    (sa_types.CHAR, "char"),
    (sa_types.Unicode, "varchar"),
    (sa_types.String, "varchar"),
    (sa_types.Uuid, "uuid"),
    (sa_types.JSON, "json"),
]

DIALECT_TYPE_MAP: dict[tuple[str, str], str] = {
    ("postgresql", "JSONB"): "jsonb",
    ("postgresql", "JSON"): "json",
    ("postgresql", "UUID"): "uuid",
    ("postgresql", "INET"): "inet",
    ("postgresql", "CIDR"): "cidr",
    ("postgresql", "MACADDR"): "macaddr",
    ("postgresql", "MACADDR8"): "macaddr8",
    ("postgresql", "INTERVAL"): "interval",
    ("postgresql", "TSVECTOR"): "tsvector",
    ("postgresql", "TSQUERY"): "tsquery",
    ("postgresql", "BYTEA"): "bytea",
    ("postgresql", "ENUM"): "enum",
    ("postgresql", "XML"): "xml",
    ("postgresql", "MONEY"): "money",
    ("postgresql", "OID"): "oid",
    ("postgresql", "INT4RANGE"): "int4range",
    ("postgresql", "INT8RANGE"): "int8range",
    ("postgresql", "NUMRANGE"): "numrange",
    ("postgresql", "TSRANGE"): "tsrange",
    ("postgresql", "TSTZRANGE"): "tstzrange",
    ("postgresql", "DATERANGE"): "daterange",
}


def _extract_params(sa_type: Any) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if getattr(sa_type, "length", None) is not None:
        params["length"] = sa_type.length
    if getattr(sa_type, "precision", None) is not None:
        params["precision"] = sa_type.precision
    if getattr(sa_type, "scale", None) is not None:
        params["scale"] = sa_type.scale
    return params


def resolve_type(dialect_name: str, sa_type: Any) -> TypeNode:
    """Map a SQLAlchemy type object to a TypeNode tree.

    Raises UnknownTypeError if no mapping is found for a leaf type.
    """
    # ARRAY is recursive; do it before any flat lookup.
    if isinstance(sa_type, sa_types.ARRAY):
        item_node = resolve_type(dialect_name, sa_type.item_type)
        return TypeNode(
            data_type_code="array",
            type_params={},
            children=[TypeChild(slot=ARRAY_ITEM_SLOT, node=item_node)],
        )

    # PG BIT branches on .varying; not amenable to the flat dialect map.
    if dialect_name == "postgresql" and isinstance(sa_type, pg.BIT):
        code = "varbit" if getattr(sa_type, "varying", False) else "bit"
        return TypeNode(data_type_code=code, type_params=_extract_params(sa_type))

    # Timezone-aware time/timestamp special-case (PG only).
    if dialect_name == "postgresql":
        if isinstance(sa_type, sa_types.DateTime) and getattr(
            sa_type, "timezone", False
        ):
            return TypeNode(
                data_type_code="timestamptz", type_params=_extract_params(sa_type)
            )
        if isinstance(sa_type, sa_types.Time) and getattr(
            sa_type, "timezone", False
        ):
            return TypeNode(
                data_type_code="timetz", type_params=_extract_params(sa_type)
            )

    cls_name = type(sa_type).__name__
    code = DIALECT_TYPE_MAP.get((dialect_name, cls_name))
    if code is None:
        for sa_class, generic_code in GENERIC_TYPE_MAP:
            if isinstance(sa_type, sa_class):
                code = generic_code
                break
    if code is None:
        raise UnknownTypeError(dialect_name, sa_type)
    return TypeNode(data_type_code=code, type_params=_extract_params(sa_type))
```

- [ ] **Step 2: Run the type_map test suite to verify it passes**

```bash
cd crawler && uv run pytest tests/test_type_map.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add crawler/aide_crawler/type_map.py crawler/tests/test_type_map.py
git commit -m "feat(crawler): TypeNode tree + ARRAY/tz/extended PG mappings"
```

---

### Task 4: Update normalizer to carry `type_node`

**Files:**
- Modify: `crawler/aide_crawler/normalizer.py`
- Modify: `crawler/tests/test_normalizer.py`

- [ ] **Step 1: Update the normalizer module**

```python
# crawler/aide_crawler/normalizer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aide_crawler.inspector import InspectionResult
from aide_crawler.type_map import TypeNode, resolve_type


@dataclass
class NormalizedField:
    name: str
    path: str
    nullable: bool
    position: int
    type_node: TypeNode


@dataclass
class NormalizedDataset:
    object_name: str
    catalog_name: str | None
    schema_name: str
    table_name: str
    is_view: bool
    pk_columns: list[str]
    uq_constraints: list[dict[str, Any]]
    comment: str | None
    fields: list[NormalizedField]
    indexes: list[dict[str, Any]]
    foreign_keys: list[dict[str, Any]]


@dataclass
class NormalizedResult:
    dialect_name: str
    datasets: list[NormalizedDataset]


def normalize(inspection: InspectionResult) -> NormalizedResult:
    """Map raw inspection output to normalized structures ready for SDK."""
    datasets: list[NormalizedDataset] = []

    for table in inspection.tables:
        object_name = f"{table.schema_name}.{table.table_name}"

        fields = []
        for idx, col in enumerate(table.columns):
            type_node = resolve_type(inspection.dialect_name, col.type)
            fields.append(
                NormalizedField(
                    name=col.name,
                    path=col.name,
                    nullable=bool(col.nullable),
                    position=idx,
                    type_node=type_node,
                )
            )

        datasets.append(
            NormalizedDataset(
                object_name=object_name,
                catalog_name=inspection.database_name,
                schema_name=table.schema_name,
                table_name=table.table_name,
                is_view=table.is_view,
                pk_columns=table.pk_columns,
                uq_constraints=table.unique_constraints,
                comment=table.comment,
                fields=fields,
                indexes=table.indexes,
                foreign_keys=table.foreign_keys,
            )
        )

    return NormalizedResult(
        dialect_name=inspection.dialect_name,
        datasets=datasets,
    )
```

- [ ] **Step 2: Update the normalizer tests**

```python
# crawler/tests/test_normalizer.py
from sqlalchemy import types as sa_types

from aide_crawler.inspector import ColumnInfo, InspectionResult, TableInfo
from aide_crawler.normalizer import normalize


def _ins(columns: list[ColumnInfo], *, is_view: bool = False) -> InspectionResult:
    return InspectionResult(
        dialect_name="postgresql",
        database_name="testdb",
        schemas=["public"],
        tables=[
            TableInfo(
                schema_name="public",
                table_name="t",
                is_view=is_view,
                columns=columns,
                pk_columns=[c.name for c in columns if c.name == "id"],
                unique_constraints=[],
                foreign_keys=[],
                indexes=[],
                comment=None,
            )
        ],
    )


def _col(name: str, type_, nullable: bool = True) -> ColumnInfo:
    return ColumnInfo(
        name=name, type=type_, nullable=nullable, default=None, comment=None
    )


def test_normalize_single_table():
    result = normalize(
        _ins(
            [
                _col("id", sa_types.Integer(), nullable=False),
                _col("name", sa_types.String(length=100), nullable=False),
            ]
        )
    )
    assert len(result.datasets) == 1
    ds = result.datasets[0]
    assert ds.object_name == "public.t"
    assert ds.catalog_name == "testdb"
    assert ds.fields[0].type_node.data_type_code == "integer"
    assert ds.fields[1].type_node.data_type_code == "varchar"
    assert ds.fields[1].type_node.type_params == {"length": 100}


def test_normalize_view():
    result = normalize(
        _ins([_col("id", sa_types.Integer(), nullable=False)], is_view=True)
    )
    assert result.datasets[0].is_view is True


def test_normalize_preserves_nullable_and_position():
    result = normalize(
        _ins(
            [
                _col("id", sa_types.BigInteger(), nullable=False),
                _col("note", sa_types.Text(), nullable=True),
            ]
        )
    )
    fields = result.datasets[0].fields
    assert fields[0].position == 0
    assert fields[0].nullable is False
    assert fields[0].type_node.data_type_code == "bigint"
    assert fields[1].position == 1
    assert fields[1].nullable is True
    assert fields[1].type_node.data_type_code == "text"


def test_normalize_array_column_produces_tree():
    result = normalize(
        _ins([_col("tags", sa_types.ARRAY(sa_types.Text()), nullable=False)])
    )
    node = result.datasets[0].fields[0].type_node
    assert node.data_type_code == "array"
    assert len(node.children) == 1
    assert node.children[0].slot == "item"
    assert node.children[0].node.data_type_code == "text"
```

- [ ] **Step 3: Run the normalizer suite**

```bash
cd crawler && uv run pytest tests/test_normalizer.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add crawler/aide_crawler/normalizer.py crawler/tests/test_normalizer.py
git commit -m "feat(crawler): NormalizedField carries TypeNode"
```

---

### Task 5: Failing applier test for ARRAY tree creation

**Files:**
- Modify: `crawler/tests/test_applier.py`

- [ ] **Step 1: Replace the `_nf` helper and add the ARRAY test**

Open `crawler/tests/test_applier.py`. Replace the `from aide_crawler.type_map import TypeMapping` import with:

```python
from aide_crawler.type_map import TypeChild, TypeNode
```

Replace the `_nf` helper (lines ~63-77) with:

```python
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
```

Append the ARRAY test at the end of the file:

```python
@pytest.mark.asyncio
async def test_array_field_creates_two_type_instances_with_parent_link():
    """Array column → root TI for 'array' + child TI for element type with slot='item'."""
    array_field = _nf(
        "tags",
        code="array",
        position=0,
        children=[
            TypeChild(slot="item", node=TypeNode(data_type_code="text", type_params={})),
        ],
    )
    nd = _nd(fields=[array_field])
    cache = _Cache(["array", "text"])
    array_dt_id = cache._by_code["array"]
    text_dt_id = cache._by_code["text"]

    # Each call to type_instances.create returns a fresh id, but we need the
    # parent id to assert linkage. Capture ids in order.
    created_ids: list[uuid.UUID] = []

    async def _create_ti(payload):
        new_id = uuid.uuid4()
        created_ids.append(new_id)
        return _obj(id=new_id)

    client = _mock_client()
    client.type_instances.create = AsyncMock(side_effect=_create_ti)

    await apply_new_datasets(
        client, system_id=SYSTEM_ID, datasets=[nd], type_cache=cache
    )

    assert client.type_instances.create.call_count == 2
    first_call = client.type_instances.create.call_args_list[0][0][0]
    second_call = client.type_instances.create.call_args_list[1][0][0]

    assert first_call.data_type_id == array_dt_id
    assert first_call.parent_id is None
    assert first_call.slot is None

    assert second_call.data_type_id == text_dt_id
    assert second_call.parent_id == created_ids[0]
    assert second_call.slot == "item"

    binding_call = client.field_bindings.create.call_args[0][0]
    assert binding_call.type_instance_id == created_ids[0]
```

- [ ] **Step 2: Run applier tests; expect failures from the ARRAY test and any existing test that referenced `TypeMapping` (none should remain after the helper update — verify)**

```bash
cd crawler && uv run pytest tests/test_applier.py -v
```

Expected: existing tests continue to pass (helper still constructs valid `NormalizedField`s); the new `test_array_field_creates_two_type_instances_with_parent_link` fails because applier still creates only one TI per field.

---

### Task 6: Implement recursive TypeInstance creation in applier

**Files:**
- Modify: `crawler/aide_crawler/applier.py`

- [ ] **Step 1: Replace the file**

```python
# crawler/aide_crawler/applier.py
from __future__ import annotations

import uuid
from dataclasses import dataclass

from aide_schemas.dataset import DatasetRdbmsCreate
from aide_schemas.dataset_schema import DatasetSchemaCreate
from aide_schemas.field import FieldCreate
from aide_schemas.field_binding import FieldBindingCreate
from aide_schemas.type_instance import TypeInstanceCreate

from aide_crawler.normalizer import NormalizedDataset
from aide_crawler.type_cache import TypeCache
from aide_crawler.type_map import TypeNode


@dataclass
class AppliedDataset:
    object_name: str
    dataset_id: uuid.UUID
    dataset_schema_id: uuid.UUID
    fields_count: int


async def _find_or_create_schema_v1(client, *, dataset_id: uuid.UUID) -> uuid.UUID:
    """Return the id of the version_num=1 schema, creating it if absent."""
    page_num = 1
    while True:
        resp = await client.dataset_schemas.list(
            page=page_num,
            size=100,
            params={"dataset_id": str(dataset_id)},
        )
        for item in resp.items:
            if item.version_num == 1:
                return item.id
        if page_num >= resp.pages:
            break
        page_num += 1

    created = await client.dataset_schemas.create(
        DatasetSchemaCreate(  # type: ignore[call-arg]
            dataset_id=dataset_id, version_num=1
        )
    )
    return created.id


async def _list_fields_map(client, *, dataset_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Return {field_name: field_id} for all fields of the dataset."""
    result: dict[str, uuid.UUID] = {}
    page_num = 1
    while True:
        resp = await client.fields.list(
            page=page_num,
            size=100,
            params={"dataset_id": str(dataset_id)},
        )
        for item in resp.items:
            result[item.name] = item.id
        if page_num >= resp.pages:
            break
        page_num += 1
    return result


async def _list_bindings_field_ids(client, *, schema_id: uuid.UUID) -> set[uuid.UUID]:
    """Return set of field_ids already bound to the given schema."""
    result: set[uuid.UUID] = set()
    page_num = 1
    while True:
        resp = await client.field_bindings.list(
            page=page_num,
            size=100,
            params={"dataset_schema_id": str(schema_id)},
        )
        for item in resp.items:
            result.add(item.field_id)
        if page_num >= resp.pages:
            break
        page_num += 1
    return result


async def _create_type_instance_tree(
    client,
    *,
    node: TypeNode,
    type_cache: TypeCache,
    parent_id: uuid.UUID | None = None,
    slot: str | None = None,
) -> uuid.UUID:
    """Create a TypeInstance for `node` and recurse into its children.

    Returns the id of the root TypeInstance (the one bound to the field).
    """
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


async def apply_new_datasets(
    client,
    *,
    system_id: uuid.UUID,
    datasets: list[NormalizedDataset],
    type_cache: TypeCache,
    existing_dataset_ids: dict[str, uuid.UUID] | None = None,
) -> list[AppliedDataset]:
    """Write the full ER chain for each new dataset.

    Idempotent: safe to rerun after a partial failure.
    """
    existing_dataset_ids = existing_dataset_ids or {}
    results: list[AppliedDataset] = []

    for nd in datasets:
        # --- Dataset ---
        if nd.object_name in existing_dataset_ids:
            dataset_id = existing_dataset_ids[nd.object_name]
        else:
            uq = {"items": nd.uq_constraints} if nd.uq_constraints else None
            created_ds = await client.datasets.create(
                DatasetRdbmsCreate(
                    kind="rdbms",
                    system_id=system_id,
                    object_name=nd.object_name,
                    catalog_name=nd.catalog_name,
                    schema_name=nd.schema_name,
                    table_name=nd.table_name,
                    is_view=nd.is_view,
                    pk_columns=nd.pk_columns,
                    uq_constraints=uq,
                )
            )
            dataset_id = created_ds.id

        # --- DatasetSchema v1 ---
        schema_id = await _find_or_create_schema_v1(client, dataset_id=dataset_id)

        # --- Fields ---
        existing_fields = await _list_fields_map(client, dataset_id=dataset_id)
        existing_bindings = await _list_bindings_field_ids(client, schema_id=schema_id)

        fields_written = 0
        for nf in nd.fields:
            if nf.name in existing_fields:
                field_id = existing_fields[nf.name]
            else:
                created_field = await client.fields.create(
                    FieldCreate(
                        dataset_id=dataset_id,
                        name=nf.name,
                        path=nf.path,
                    )
                )
                field_id = created_field.id

            if field_id in existing_bindings:
                fields_written += 1
                continue

            root_ti_id = await _create_type_instance_tree(
                client,
                node=nf.type_node,
                type_cache=type_cache,
            )
            await client.field_bindings.create(
                FieldBindingCreate(
                    field_id=field_id,
                    dataset_schema_id=schema_id,
                    type_instance_id=root_ti_id,
                    position=nf.position,
                    is_nullable=nf.nullable,
                )
            )
            fields_written += 1

        results.append(
            AppliedDataset(
                object_name=nd.object_name,
                dataset_id=dataset_id,
                dataset_schema_id=schema_id,
                fields_count=fields_written,
            )
        )

    return results
```

- [ ] **Step 2: Run the full crawler suite**

```bash
cd crawler && uv run pytest tests/ -v
```

Expected: all tests pass, including `test_array_field_creates_two_type_instances_with_parent_link`.

- [ ] **Step 3: Commit**

```bash
git add crawler/aide_crawler/applier.py crawler/tests/test_applier.py
git commit -m "feat(crawler): recursive TypeInstance creation for compound types"
```

---

### Task 7: Lint + type-check sweep

**Files:** none new

- [ ] **Step 1: Run repo lint and type checks**

```bash
make check
```

Expected: clean. If `mypy` complains about the new `TypeNode` use-sites or `UnknownTypeError(sa_type: Any)`, fix annotations inline.

- [ ] **Step 2: Auto-format**

```bash
make format
```

- [ ] **Step 3: Commit any formatting/lint changes (only if non-empty)**

```bash
git status
# if changes:
git add -A
git commit -m "chore(crawler): format after type-map refactor"
```

---

### Task 8: Extend manual seed for regression coverage

**Files:**
- Modify: `scripts/manual_test/seed_target.sh`

- [ ] **Step 1: Add a `types_zoo` table covering the new mappings**

After the existing `INSERT INTO demo.products …` block (before the closing `\dt demo.*`), insert:

```bash
CREATE TABLE demo.types_zoo (
    id              bigserial PRIMARY KEY,
    code_char       char(8),
    bits_fixed      bit(8),
    bits_varying    bit varying(16),
    money_amount    money,
    macaddr8_addr   macaddr8,
    text_search     tsvector,
    text_query      tsquery,
    xml_blob        xml,
    int4_window     int4range,
    int8_window     int8range,
    num_window      numrange,
    ts_window       tsrange,
    tstz_window     tstzrange,
    date_window     daterange,
    ts_with_tz      timestamptz,
    time_with_tz    timetz,
    nested_array    integer[][]
);
```

The full file ends up with `demo.products`, `demo.orders`, `demo.types_zoo` plus the existing index/insert statements. Leave the existing `\dt demo.*` line at the end.

- [ ] **Step 2: Run the seed against a fresh target to make sure SQL is valid**

```bash
./scripts/manual_test/start_pg14.sh
./scripts/manual_test/seed_target.sh
```

Expected: seed completes without errors and `\dt demo.*` lists all three tables.

- [ ] **Step 3: Commit**

```bash
git add scripts/manual_test/seed_target.sh
git commit -m "test(crawler): seed_target covers PG14 type mappings"
```

---

### Task 9: Manual end-to-end verification

**Files:** none

- [ ] **Step 1: Bring up metastore + seed flavor data**

```bash
make up
make alembic-head
uv run python -m backend.scripts.seed_data_types --file backend/scripts/data/postgres14.yaml
```

- [ ] **Step 2: Confirm a system with `flavor_code=postgres14` exists** (create via Swagger if needed). Note its `code` value.

- [ ] **Step 3: Run the crawler against the seeded target**

```bash
cd crawler
uv run aide-crawler crawl \
  --system-code <system_code> \
  --connection-url "postgresql+psycopg://crawler:crawler@localhost:5434/target" \
  --metastore-url http://localhost:8000 \
  --metastore-user <user> \
  --metastore-password <pw> \
  --schemas demo \
  --format text
```

Expected: exits 0; report lists `demo.products`, `demo.orders`, `demo.types_zoo` as new datasets; no `UnknownTypeError`.

- [ ] **Step 4: Spot-check the metastore**

Hit the metastore (Swagger or curl) for one array-bearing field, e.g. `demo.products.tags`:
- `GET /api/v1/fields?dataset_id=<products_id>` → find `tags` field id
- `GET /api/v1/field_bindings?dataset_schema_id=<schema_id>` → find binding for that field, note `type_instance_id`
- `GET /api/v1/type_instances/<id>` → `data_type_id` resolves to `data_types.code = "array"`, `parent_id = null`
- `GET /api/v1/type_instances?parent_id=<root_id>` → one child with `slot = "item"`, `data_type_id` resolving to `text`

Same spot-check on `types_zoo.nested_array`: 3-level chain (`array → item → array → item → integer`).

If anything diverges from the expectation, return to the relevant task and fix. Otherwise the work is done.
