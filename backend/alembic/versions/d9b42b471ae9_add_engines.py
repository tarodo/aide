"""add engines

Revision ID: d9b42b471ae9
Revises: 3d8c5832ff76
Create Date: 2026-04-30 08:59:51.270386

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d9b42b471ae9"
down_revision: Union[str, Sequence[str], None] = "3d8c5832ff76"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "engines",
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint("role IN ('cdc', 'compute')", name="ck_engines_role"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_engines_created_by"), "engines", ["created_by"], unique=False
    )
    op.create_index(
        op.f("ix_engines_deleted_at"), "engines", ["deleted_at"], unique=False
    )
    op.create_index(op.f("ix_engines_id"), "engines", ["id"], unique=True)
    op.create_index(op.f("ix_engines_kind"), "engines", ["kind"], unique=False)
    op.create_index(op.f("ix_engines_role"), "engines", ["role"], unique=False)
    op.create_index(
        op.f("ix_engines_updated_by"), "engines", ["updated_by"], unique=False
    )
    op.create_index(
        "uq_engines_code_active",
        "engines",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "engine_debezium",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "envelope_template",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "topic_routing",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["id"], ["engines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "engine_ogg",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "envelope_template",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "topic_routing",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["id"], ["engines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "engine_spark",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "runtime_opts",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["id"], ["engines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "engine_impala",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "runtime_opts",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["id"], ["engines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("dataset_links", sa.Column("engine_id", sa.UUID(), nullable=True))
    op.create_index(
        "ix_dataset_links_engine_id",
        "dataset_links",
        ["engine_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_dataset_links_engine_id_engines",
        "dataset_links",
        "engines",
        ["engine_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_dataset_links_engine_id_engines", "dataset_links", type_="foreignkey"
    )
    op.drop_index("ix_dataset_links_engine_id", table_name="dataset_links")
    op.drop_column("dataset_links", "engine_id")

    op.drop_table("engine_impala")
    op.drop_table("engine_spark")
    op.drop_table("engine_ogg")
    op.drop_table("engine_debezium")

    op.drop_index(
        "uq_engines_code_active",
        table_name="engines",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(op.f("ix_engines_updated_by"), table_name="engines")
    op.drop_index(op.f("ix_engines_role"), table_name="engines")
    op.drop_index(op.f("ix_engines_kind"), table_name="engines")
    op.drop_index(op.f("ix_engines_id"), table_name="engines")
    op.drop_index(op.f("ix_engines_deleted_at"), table_name="engines")
    op.drop_index(op.f("ix_engines_created_by"), table_name="engines")
    op.drop_table("engines")
