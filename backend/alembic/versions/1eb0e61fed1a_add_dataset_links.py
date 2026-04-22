"""add dataset links

Revision ID: 1eb0e61fed1a
Revises: fdca55926c40
Create Date: 2026-04-22 07:43:53.259270

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "1eb0e61fed1a"
down_revision: Union[str, Sequence[str], None] = "fdca55926c40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dataset_links",
        sa.Column("source_dataset_id", sa.UUID(), nullable=False),
        sa.Column("target_dataset_id", sa.UUID(), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.Column(
            "row_version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.CheckConstraint(
            "source_dataset_id <> target_dataset_id", name="ck_dataset_link_no_self"
        ),
        sa.ForeignKeyConstraint(["source_dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["target_dataset_id"], ["datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dataset_links_id"), "dataset_links", ["id"], unique=True)
    op.create_index(
        op.f("ix_dataset_links_source_dataset_id"),
        "dataset_links",
        ["source_dataset_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dataset_links_target_dataset_id"),
        "dataset_links",
        ["target_dataset_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dataset_links_created_by"),
        "dataset_links",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dataset_links_updated_by"),
        "dataset_links",
        ["updated_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dataset_links_deleted_at"),
        "dataset_links",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "uq_dataset_link_pair_active",
        "dataset_links",
        ["source_dataset_id", "target_dataset_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_dataset_link_pair_active", table_name="dataset_links")
    op.drop_index(op.f("ix_dataset_links_deleted_at"), table_name="dataset_links")
    op.drop_index(op.f("ix_dataset_links_updated_by"), table_name="dataset_links")
    op.drop_index(op.f("ix_dataset_links_created_by"), table_name="dataset_links")
    op.drop_index(
        op.f("ix_dataset_links_target_dataset_id"), table_name="dataset_links"
    )
    op.drop_index(
        op.f("ix_dataset_links_source_dataset_id"), table_name="dataset_links"
    )
    op.drop_index(op.f("ix_dataset_links_id"), table_name="dataset_links")
    op.drop_table("dataset_links")
