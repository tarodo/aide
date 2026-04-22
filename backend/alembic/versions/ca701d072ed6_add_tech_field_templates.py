"""add_tech_field_templates

Revision ID: ca701d072ed6
Revises: 9576faa64a0d
Create Date: 2026-04-22 09:40:02.527217

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ca701d072ed6"
down_revision: Union[str, Sequence[str], None] = "9576faa64a0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tech_field_templates",
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("layer", sa.String(length=32), nullable=False),
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
            "row_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        op.f("ix_tech_field_templates_id"),
        "tech_field_templates",
        ["id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_tech_field_templates_created_by"),
        "tech_field_templates",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tech_field_templates_updated_by"),
        "tech_field_templates",
        ["updated_by"],
        unique=False,
    )

    op.create_table(
        "tech_field_template_fields",
        sa.Column("template_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type_code", sa.String(length=64), nullable=False),
        sa.Column(
            "order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
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
            "row_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["tech_field_templates.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "name", name="uq_tft_field_name"),
    )
    op.create_index(
        op.f("ix_tech_field_template_fields_id"),
        "tech_field_template_fields",
        ["id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_tech_field_template_fields_template_id"),
        "tech_field_template_fields",
        ["template_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tech_field_template_fields_created_by"),
        "tech_field_template_fields",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tech_field_template_fields_updated_by"),
        "tech_field_template_fields",
        ["updated_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tech_field_template_fields_updated_by"),
        table_name="tech_field_template_fields",
    )
    op.drop_index(
        op.f("ix_tech_field_template_fields_created_by"),
        table_name="tech_field_template_fields",
    )
    op.drop_index(
        op.f("ix_tech_field_template_fields_template_id"),
        table_name="tech_field_template_fields",
    )
    op.drop_index(
        op.f("ix_tech_field_template_fields_id"),
        table_name="tech_field_template_fields",
    )
    op.drop_table("tech_field_template_fields")
    op.drop_index(
        op.f("ix_tech_field_templates_updated_by"),
        table_name="tech_field_templates",
    )
    op.drop_index(
        op.f("ix_tech_field_templates_created_by"),
        table_name="tech_field_templates",
    )
    op.drop_index(
        op.f("ix_tech_field_templates_id"),
        table_name="tech_field_templates",
    )
    op.drop_table("tech_field_templates")
