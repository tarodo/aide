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
