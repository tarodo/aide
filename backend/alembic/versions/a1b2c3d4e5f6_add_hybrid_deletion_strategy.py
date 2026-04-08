"""add hybrid deletion strategy

Revision ID: a1b2c3d4e5f6
Revises: 3d4daf44f3fa
Create Date: 2026-04-08 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "3d4daf44f3fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables that get soft-delete columns
SOFT_DELETE_TABLES = [
    "system_kinds",
    "system_flavors",
    "systems",
    "datasets",
    "data_types",
    "credential_refs",
]

# Old unique constraints/indexes to drop, and new partial indexes to create
UNIQUE_CONSTRAINT_CHANGES = [
    # (table, old_constraint_name, old_is_index, new_index_name, columns)
    (
        "system_kinds",
        "ix_system_kinds_code",
        True,
        "uq_system_kinds_code_active",
        ["code"],
    ),
    (
        "system_flavors",
        "ix_system_flavors_code",
        True,
        "uq_system_flavors_code_active",
        ["code"],
    ),
    ("systems", "ix_systems_code", True, "uq_systems_code_active", ["code"]),
    (
        "datasets",
        "idx_dataset_system_id_object_name",
        False,
        "uq_datasets_system_id_object_name_active",
        ["system_id", "object_name"],
    ),
    (
        "data_types",
        "idx_data_type_system_flavor_id_code",
        False,
        "uq_data_types_sfid_code_active",
        ["system_flavor_id", "code"],
    ),
    (
        "credential_refs",
        "idx_credential_ref_provider_path",
        False,
        "uq_credential_refs_provider_path_active",
        ["provider", "path"],
    ),
]

# FK constraints to change to ON DELETE CASCADE
# (table, constraint_name, column, referred_table, referred_column)
CASCADE_FK_CHANGES = [
    ("fields", "fields_dataset_id_fkey", "dataset_id", "datasets", "id"),
    (
        "dataset_schemas",
        "dataset_schemas_dataset_id_fkey",
        "dataset_id",
        "datasets",
        "id",
    ),
    ("field_bindings", "field_bindings_field_id_fkey", "field_id", "fields", "id"),
    (
        "field_bindings",
        "field_bindings_dataset_schema_id_fkey",
        "dataset_schema_id",
        "dataset_schemas",
        "id",
    ),
    (
        "field_bindings",
        "field_bindings_data_type_id_fkey",
        "data_type_id",
        "data_types",
        "id",
    ),
    (
        "cast_rules",
        "cast_rules_source_data_type_id_fkey",
        "source_data_type_id",
        "data_types",
        "id",
    ),
    (
        "cast_rules",
        "cast_rules_target_data_type_id_fkey",
        "target_data_type_id",
        "data_types",
        "id",
    ),
]


def upgrade() -> None:
    # 1. Add soft-delete columns to core tables
    for table in SOFT_DELETE_TABLES:
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True))
        op.add_column(table, sa.Column("deleted_by", sa.UUID(), nullable=True))
        op.create_index(
            op.f(f"ix_{table}_deleted_at"), table, ["deleted_at"], unique=False
        )

    # 2. Drop old unique constraints/indexes and create partial unique indexes
    for table, old_name, old_is_index, new_name, columns in UNIQUE_CONSTRAINT_CHANGES:
        if old_is_index:
            op.drop_index(old_name, table_name=table)
        else:
            op.drop_constraint(old_name, table, type_="unique")
        op.create_index(
            new_name,
            table,
            columns,
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        )

    # 3. Change FK constraints on leaf tables to ON DELETE CASCADE
    for table, fk_name, column, ref_table, ref_column in CASCADE_FK_CHANGES:
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            table,
            ref_table,
            [column],
            [ref_column],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    # 3. Revert FK constraints to RESTRICT (no ondelete)
    for table, fk_name, column, ref_table, ref_column in reversed(CASCADE_FK_CHANGES):
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            table,
            ref_table,
            [column],
            [ref_column],
        )

    # 2. Drop partial unique indexes and recreate old unique constraints/indexes
    for table, old_name, old_is_index, new_name, columns in reversed(
        UNIQUE_CONSTRAINT_CHANGES
    ):
        op.drop_index(new_name, table_name=table)
        if old_is_index:
            op.create_index(old_name, table, columns, unique=True)
        else:
            op.create_unique_constraint(old_name, table, columns)

    # 1. Drop soft-delete columns
    for table in reversed(SOFT_DELETE_TABLES):
        op.drop_index(op.f(f"ix_{table}_deleted_at"), table_name=table)
        op.drop_column(table, "deleted_by")
        op.drop_column(table, "deleted_at")
