"""add lineage pins (migration A — nullable)

Additive step: add source_schema_id / target_schema_id on dataset_links (nullable),
add origin on fields (nullable, server_default='mapped'). Keeps is_tech for now.

Revision ID: 6e67d11c0464
Revises: ca701d072ed6
Create Date: 2026-04-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "6e67d11c0464"
down_revision = "ca701d072ed6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # dataset_links schema pins
    op.add_column(
        "dataset_links",
        sa.Column(
            "source_schema_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_schemas.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "dataset_links",
        sa.Column(
            "target_schema_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_schemas.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_dataset_links_source_schema",
        "dataset_links",
        ["source_schema_id"],
    )
    op.create_index(
        "idx_dataset_links_target_schema",
        "dataset_links",
        ["target_schema_id"],
    )

    # fields.origin with server_default so new rows never land NULL
    op.add_column(
        "fields",
        sa.Column(
            "origin",
            sa.String(20),
            nullable=True,
            server_default="mapped",
        ),
    )
    # is_tech remains for this step.
    # origin has server_default so new rows inserted between Migration A
    # and Migration B (by old or new app code) are never NULL.


def downgrade() -> None:
    op.drop_column("fields", "origin")
    op.drop_index("idx_dataset_links_target_schema", table_name="dataset_links")
    op.drop_index("idx_dataset_links_source_schema", table_name="dataset_links")
    op.drop_column("dataset_links", "target_schema_id")
    op.drop_column("dataset_links", "source_schema_id")
