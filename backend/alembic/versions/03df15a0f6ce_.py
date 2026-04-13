"""add row_version column for optimistic locking

Revision ID: 03df15a0f6ce
Revises: f6a7b8c9d0e1
Create Date: 2026-04-13 12:21:10.452474

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "03df15a0f6ce"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add row_version column to all entities for optimistic locking."""
    for table in [
        "cast_rules",
        "credential_refs",
        "data_types",
        "dataset_schemas",
        "datasets",
        "field_bindings",
        "fields",
        "system_flavors",
        "system_kinds",
        "systems",
        "type_instances",
        "users",
    ]:
        op.add_column(
            table,
            sa.Column(
                "row_version",
                sa.Integer(),
                server_default=sa.text("1"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    """Remove row_version column from all entities."""
    for table in [
        "users",
        "type_instances",
        "systems",
        "system_kinds",
        "system_flavors",
        "fields",
        "field_bindings",
        "datasets",
        "dataset_schemas",
        "data_types",
        "credential_refs",
        "cast_rules",
    ]:
        op.drop_column(table, "row_version")
