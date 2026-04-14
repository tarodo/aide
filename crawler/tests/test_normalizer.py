from sqlalchemy import types as sa_types

from aide_crawler.inspector import ColumnInfo, InspectionResult, TableInfo
from aide_crawler.normalizer import normalize


def test_normalize_single_table():
    inspection = InspectionResult(
        dialect_name="postgresql",
        database_name="testdb",
        schemas=["public"],
        tables=[
            TableInfo(
                schema_name="public",
                table_name="users",
                is_view=False,
                columns=[
                    ColumnInfo(
                        name="id",
                        type=sa_types.Integer(),
                        nullable=False,
                        default=None,
                        comment=None,
                    ),
                    ColumnInfo(
                        name="name",
                        type=sa_types.String(length=100),
                        nullable=False,
                        default=None,
                        comment="User name",
                    ),
                ],
                pk_columns=["id"],
                unique_constraints=[],
                foreign_keys=[],
                indexes=[],
                comment="Users table",
            )
        ],
    )
    result = normalize(inspection)
    assert len(result.datasets) == 1
    ds = result.datasets[0]
    assert ds.object_name == "public.users"
    assert ds.catalog_name == "testdb"
    assert ds.schema_name == "public"
    assert ds.table_name == "users"
    assert ds.is_view is False
    assert ds.pk_columns == ["id"]
    assert len(ds.fields) == 2
    assert ds.fields[0].name == "id"
    assert ds.fields[0].type_mapping is not None
    assert ds.fields[0].type_mapping.data_type_code == "integer"


def test_normalize_view():
    inspection = InspectionResult(
        dialect_name="postgresql",
        database_name="testdb",
        schemas=["public"],
        tables=[
            TableInfo(
                schema_name="public",
                table_name="active_users",
                is_view=True,
                columns=[
                    ColumnInfo(
                        name="id",
                        type=sa_types.Integer(),
                        nullable=False,
                        default=None,
                        comment=None,
                    ),
                ],
                pk_columns=[],
                unique_constraints=[],
                foreign_keys=[],
                indexes=[],
                comment=None,
            )
        ],
    )
    result = normalize(inspection)
    assert result.datasets[0].is_view is True
