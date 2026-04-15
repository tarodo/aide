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
