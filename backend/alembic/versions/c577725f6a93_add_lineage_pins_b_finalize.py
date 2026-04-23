"""add lineage pins (migration B — finalize)

Flips schema_ids and origin to NOT NULL and drops fields.is_tech.

WARNING: Downgrade is only safe when no Field rows have origin='deprecated'.
On downgrade, 'deprecated' maps to is_tech=False (mapped) — which violates
the Phase 1 invariant that mapped target fields must have a source FieldLink.
Hold this migration until the forward direction is stable in prod.

Revision ID: c577725f6a93
Revises: 6e67d11c0464
Create Date: 2026-04-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c577725f6a93"
down_revision = "6e67d11c0464"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("dataset_links", "source_schema_id", nullable=False)
    op.alter_column("dataset_links", "target_schema_id", nullable=False)
    op.alter_column(
        "fields",
        "origin",
        nullable=False,
        existing_type=sa.String(20),
        existing_server_default="mapped",
    )
    op.drop_column("fields", "is_tech")


def downgrade() -> None:
    # See module header WARNING — downgrade loses the DEPRECATED semantic.
    op.add_column(
        "fields",
        sa.Column(
            "is_tech",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute("UPDATE fields SET is_tech = TRUE WHERE origin = 'tech'")
    op.alter_column("fields", "origin", nullable=True)
    op.alter_column("dataset_links", "target_schema_id", nullable=True)
    op.alter_column("dataset_links", "source_schema_id", nullable=True)
