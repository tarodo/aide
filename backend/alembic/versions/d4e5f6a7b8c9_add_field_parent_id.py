"""add field parent_id for nested fields

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-09

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add parent_id column
    op.add_column(
        "fields",
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # 2. Add index on parent_id for tree queries
    op.create_index("ix_fields_parent_id", "fields", ["parent_id"])

    # 3. Drop old unique constraint
    op.drop_constraint("idx_field_dataset_id_name", "fields", type_="unique")

    # 4. Create two partial unique indexes for NULL-safe sibling uniqueness
    op.execute(
        "CREATE UNIQUE INDEX idx_field_root_name "
        "ON fields (dataset_id, name) "
        "WHERE parent_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_field_nested_name "
        "ON fields (dataset_id, parent_id, name) "
        "WHERE parent_id IS NOT NULL"
    )


def downgrade() -> None:
    # 1. Drop partial indexes
    op.execute("DROP INDEX IF EXISTS idx_field_nested_name")
    op.execute("DROP INDEX IF EXISTS idx_field_root_name")

    # 2. Restore original unique constraint
    op.create_unique_constraint(
        "idx_field_dataset_id_name", "fields", ["dataset_id", "name"]
    )

    # 3. Drop parent_id index and column
    op.drop_index("ix_fields_parent_id", "fields")
    op.drop_column("fields", "parent_id")
