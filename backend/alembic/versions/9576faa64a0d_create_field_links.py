"""create field links

Revision ID: 9576faa64a0d
Revises: 1eb0e61fed1a
Create Date: 2026-04-22 08:11:45.701078

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9576faa64a0d"
down_revision: Union[str, Sequence[str], None] = "1eb0e61fed1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "field_links",
        sa.Column("dataset_link_id", sa.UUID(), nullable=False),
        sa.Column("source_field_id", sa.UUID(), nullable=False),
        sa.Column("target_field_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "row_version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["dataset_link_id"], ["dataset_links.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_link_id",
            "source_field_id",
            "target_field_id",
            name="uq_field_link_triple",
        ),
        sa.UniqueConstraint(
            "dataset_link_id",
            "target_field_id",
            name="uq_field_link_target_in_link",
        ),
    )
    op.create_index(op.f("ix_field_links_id"), "field_links", ["id"], unique=True)
    op.create_index(
        op.f("ix_field_links_dataset_link_id"),
        "field_links",
        ["dataset_link_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_field_links_source_field_id"),
        "field_links",
        ["source_field_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_field_links_target_field_id"),
        "field_links",
        ["target_field_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_field_links_created_by"),
        "field_links",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_field_links_updated_by"),
        "field_links",
        ["updated_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_field_links_updated_by"), table_name="field_links")
    op.drop_index(op.f("ix_field_links_created_by"), table_name="field_links")
    op.drop_index(op.f("ix_field_links_target_field_id"), table_name="field_links")
    op.drop_index(op.f("ix_field_links_source_field_id"), table_name="field_links")
    op.drop_index(op.f("ix_field_links_dataset_link_id"), table_name="field_links")
    op.drop_index(op.f("ix_field_links_id"), table_name="field_links")
    op.drop_table("field_links")
