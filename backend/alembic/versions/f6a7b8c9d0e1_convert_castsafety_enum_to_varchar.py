"""convert castsafety PG enum to varchar

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-13

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert column from PG enum to varchar, lowercasing existing values
    op.execute(
        "ALTER TABLE cast_rules "
        "ALTER COLUMN safety TYPE varchar(20) USING lower(safety::text)"
    )
    # Drop the PG enum type
    op.execute("DROP TYPE IF EXISTS castsafety")


def downgrade() -> None:
    # Recreate the PG enum type
    castsafety_enum = postgresql.ENUM(
        "IMPLICIT", "SAFE", "UNSAFE", name="castsafety", create_type=False
    )
    castsafety_enum.create(op.get_bind(), checkfirst=True)
    # Convert back: uppercase varchar values to PG enum
    op.execute(
        "ALTER TABLE cast_rules "
        "ALTER COLUMN safety TYPE castsafety USING upper(safety)::castsafety"
    )
