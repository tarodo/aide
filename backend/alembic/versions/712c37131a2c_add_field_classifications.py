"""add_field_classifications

Revision ID: 712c37131a2c
Revises: 44ecd45b1230
Create Date: 2026-04-17 14:12:57.082229

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "712c37131a2c"
down_revision: Union[str, Sequence[str], None] = "44ecd45b1230"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "field_classifications",
        sa.Column("field_id", sa.UUID(), nullable=False),
        sa.Column("pii_tags", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "row_version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_field_classifications_created_by"),
        "field_classifications",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        "ix_field_classifications_field_id_created_at",
        "field_classifications",
        ["field_id", sa.text("created_at DESC")],
    )
    op.create_index(
        op.f("ix_field_classifications_id"),
        "field_classifications",
        ["id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_field_classifications_updated_by"),
        "field_classifications",
        ["updated_by"],
        unique=False,
    )
    op.drop_column("fields", "pii_tags")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "fields",
        sa.Column(
            "pii_tags",
            postgresql.ARRAY(sa.TEXT()),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.drop_index(
        op.f("ix_field_classifications_updated_by"),
        table_name="field_classifications",
    )
    op.drop_index(
        op.f("ix_field_classifications_id"), table_name="field_classifications"
    )
    op.drop_index(
        "ix_field_classifications_field_id_created_at",
        table_name="field_classifications",
    )
    op.drop_index(
        op.f("ix_field_classifications_created_by"),
        table_name="field_classifications",
    )
    op.drop_table("field_classifications")
