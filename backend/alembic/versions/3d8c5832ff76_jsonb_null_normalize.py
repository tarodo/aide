"""jsonb null normalize

Data-only migration: converts existing 'null'::jsonb documents to SQL NULL
on all nullable JSONB columns. No DDL change — none_as_null=True is a
Python-side encoder flag that requires no schema alteration.

Revision ID: 3d8c5832ff76
Revises: c577725f6a93
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op

revision = "3d8c5832ff76"
down_revision = "c577725f6a93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # datasets table (base)
    op.execute("UPDATE datasets SET extra = NULL WHERE extra = 'null'::jsonb;")
    # dataset_rdbms joined-inheritance subclass
    op.execute(
        "UPDATE dataset_rdbms SET uq_constraints = NULL WHERE uq_constraints = 'null'::jsonb;"
    )
    # dataset_hive joined-inheritance subclass
    op.execute(
        "UPDATE dataset_hive SET tblproperties = NULL WHERE tblproperties = 'null'::jsonb;"
    )
    # fields
    op.execute("UPDATE fields SET extra = NULL WHERE extra = 'null'::jsonb;")
    # systems
    op.execute("UPDATE systems SET extra = NULL WHERE extra = 'null'::jsonb;")
    # type_instances
    op.execute(
        "UPDATE type_instances SET type_params = NULL WHERE type_params = 'null'::jsonb;"
    )
    # crawl_runs
    op.execute("UPDATE crawl_runs SET summary = NULL WHERE summary = 'null'::jsonb;")
    op.execute(
        "UPDATE crawl_runs SET diff_payload = NULL WHERE diff_payload = 'null'::jsonb;"
    )
    # dataset_schemas
    op.execute("UPDATE dataset_schemas SET schema = NULL WHERE schema = 'null'::jsonb;")
    op.execute("UPDATE dataset_schemas SET extra = NULL WHERE extra = 'null'::jsonb;")


def downgrade() -> None:
    # Not reversible: converting jsonb null documents back to SQL NULL
    # loses the distinction between "no value" and an explicit null.
    pass
