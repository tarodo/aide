"""migrate field_bindings to type_instance_id

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-08 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add type_instance_id column (nullable for now)
    op.add_column(
        "field_bindings",
        sa.Column(
            "type_instance_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # Step 2: Migrate existing data — create a root TypeInstance for each FieldBinding
    conn = op.get_bind()
    bindings = conn.execute(
        sa.text(
            "SELECT id, data_type_id, type_params, created_by, updated_by, note "
            "FROM field_bindings"
        )
    ).fetchall()

    for fb in bindings:
        result = conn.execute(
            sa.text(
                "INSERT INTO type_instances "
                "(id, data_type_id, type_params, parent_id, slot, "
                " created_by, updated_by, note) "
                "VALUES (gen_random_uuid(), :data_type_id, :type_params, NULL, NULL, "
                " :created_by, :updated_by, :note) "
                "RETURNING id"
            ),
            {
                "data_type_id": fb.data_type_id,
                "type_params": fb.type_params,
                "created_by": fb.created_by,
                "updated_by": fb.updated_by,
                "note": fb.note,
            },
        )
        ti_id = result.scalar_one()
        conn.execute(
            sa.text(
                "UPDATE field_bindings SET type_instance_id = :ti_id WHERE id = :fb_id"
            ),
            {"ti_id": ti_id, "fb_id": fb.id},
        )

    # Step 3: Make type_instance_id NOT NULL, add FK and index
    op.alter_column("field_bindings", "type_instance_id", nullable=False)
    op.create_foreign_key(
        "fk_field_bindings_type_instance_id",
        "field_bindings",
        "type_instances",
        ["type_instance_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_field_bindings_type_instance_id",
        "field_bindings",
        ["type_instance_id"],
    )

    # Step 4: Drop old columns
    op.drop_constraint(
        "field_bindings_data_type_id_fkey", "field_bindings", type_="foreignkey"
    )
    op.drop_index("ix_field_bindings_data_type_id", table_name="field_bindings")
    op.drop_column("field_bindings", "data_type_id")
    op.drop_column("field_bindings", "type_params")


def downgrade() -> None:
    # Step 1: Re-add old columns
    op.add_column(
        "field_bindings",
        sa.Column(
            "data_type_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "field_bindings",
        sa.Column("type_params", postgresql.JSONB(), nullable=True),
    )

    # Step 2: Migrate data back from type_instances
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE field_bindings fb "
            "SET data_type_id = ti.data_type_id, type_params = ti.type_params "
            "FROM type_instances ti "
            "WHERE fb.type_instance_id = ti.id"
        )
    )

    # Step 3: Make data_type_id NOT NULL, add FK and index
    op.alter_column("field_bindings", "data_type_id", nullable=False)
    op.create_foreign_key(
        "field_bindings_data_type_id_fkey",
        "field_bindings",
        "data_types",
        ["data_type_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_field_bindings_data_type_id",
        "field_bindings",
        ["data_type_id"],
    )

    # Step 4: Delete migrated type instances, drop type_instance_id column
    conn.execute(
        sa.text(
            "DELETE FROM type_instances ti "
            "USING field_bindings fb "
            "WHERE fb.type_instance_id = ti.id"
        )
    )
    op.drop_index("ix_field_bindings_type_instance_id", table_name="field_bindings")
    op.drop_constraint(
        "fk_field_bindings_type_instance_id", "field_bindings", type_="foreignkey"
    )
    op.drop_column("field_bindings", "type_instance_id")
