from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, inspect


DEFAULT_EXCLUDE_SCHEMAS: dict[str, set[str]] = {
    "postgresql": {"information_schema", "pg_catalog", "pg_toast"},
    "mysql": {"information_schema", "mysql", "performance_schema", "sys"},
    "default": {"information_schema"},
}


@dataclass
class ColumnInfo:
    name: str
    type: Any
    nullable: bool
    default: str | None
    comment: str | None


@dataclass
class TableInfo:
    schema_name: str
    table_name: str
    is_view: bool
    columns: list[ColumnInfo]
    pk_columns: list[str]
    unique_constraints: list[dict[str, Any]]
    foreign_keys: list[dict[str, Any]]
    indexes: list[dict[str, Any]]
    comment: str | None


@dataclass
class InspectionResult:
    dialect_name: str
    database_name: str | None
    schemas: list[str]
    tables: list[TableInfo]


def run_inspection(
    connection_url: str,
    *,
    include_schemas: list[str] | None = None,
    exclude_schemas: list[str] | None = None,
    include_tables: list[str] | None = None,
    exclude_tables: list[str] | None = None,
) -> InspectionResult:
    """
    Connect to RDBMS and collect metadata via SQLAlchemy Inspector.
    Uses sync engine since inspect() does not support async.
    """
    engine = create_engine(connection_url)
    insp = inspect(engine)
    dialect_name = engine.dialect.name

    database_name: str | None = None
    url = engine.url
    if url.database:
        database_name = url.database

    all_schemas = insp.get_schema_names()
    system_schemas = DEFAULT_EXCLUDE_SCHEMAS.get(
        dialect_name, DEFAULT_EXCLUDE_SCHEMAS["default"]
    )

    if include_schemas:
        target_schemas = [s for s in include_schemas if s in all_schemas]
    else:
        excluded = system_schemas | set(exclude_schemas or [])
        target_schemas = [s for s in all_schemas if s not in excluded]

    exclude_table_set = set(exclude_tables or [])
    include_table_set: set[str] | None = (
        set(include_tables) if include_tables else None
    )
    tables: list[TableInfo] = []

    def _should_include(schema: str, name: str) -> bool:
        if include_table_set is not None:
            qualified = f"{schema}.{name}"
            if name not in include_table_set and qualified not in include_table_set:
                return False
        if name in exclude_table_set or f"{schema}.{name}" in exclude_table_set:
            return False
        return True

    for schema in target_schemas:
        for table_name in insp.get_table_names(schema=schema):
            if not _should_include(schema, table_name):
                continue
            table_info = _inspect_table(insp, schema, table_name, is_view=False)
            tables.append(table_info)

        for view_name in insp.get_view_names(schema=schema):
            if not _should_include(schema, view_name):
                continue
            table_info = _inspect_table(insp, schema, view_name, is_view=True)
            tables.append(table_info)

    engine.dispose()

    return InspectionResult(
        dialect_name=dialect_name,
        database_name=database_name,
        schemas=target_schemas,
        tables=tables,
    )


def _inspect_table(
    insp: Any,
    schema: str,
    table_name: str,
    *,
    is_view: bool,
) -> TableInfo:
    columns = []
    for col in insp.get_columns(table_name, schema=schema):
        columns.append(
            ColumnInfo(
                name=col["name"],
                type=col["type"],
                nullable=col.get("nullable", True),
                default=col.get("default"),
                comment=col.get("comment"),
            )
        )

    pk_constraint = insp.get_pk_constraint(table_name, schema=schema)
    pk_columns = pk_constraint.get("constrained_columns", []) if pk_constraint else []

    try:
        unique_constraints = insp.get_unique_constraints(table_name, schema=schema)
    except NotImplementedError:
        unique_constraints = []

    foreign_keys = insp.get_foreign_keys(table_name, schema=schema)
    indexes = insp.get_indexes(table_name, schema=schema)

    try:
        comment_info = insp.get_table_comment(table_name, schema=schema)
        comment = comment_info.get("text") if comment_info else None
    except NotImplementedError:
        comment = None

    return TableInfo(
        schema_name=schema,
        table_name=table_name,
        is_view=is_view,
        columns=columns,
        pk_columns=pk_columns,
        unique_constraints=[
            {"name": uc.get("name"), "columns": uc.get("column_names", [])}
            for uc in unique_constraints
        ],
        foreign_keys=[
            {
                "name": fk.get("name"),
                "constrained_columns": fk.get("constrained_columns", []),
                "referred_schema": fk.get("referred_schema"),
                "referred_table": fk.get("referred_table"),
                "referred_columns": fk.get("referred_columns", []),
            }
            for fk in foreign_keys
        ],
        indexes=[
            {
                "name": idx.get("name"),
                "columns": idx.get("column_names", []),
                "unique": idx.get("unique", False),
            }
            for idx in indexes
        ],
        comment=comment,
    )
