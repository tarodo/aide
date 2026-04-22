"""add_pattern_code_to_datasets

Revision ID: fdca55926c40
Revises: 02153a312b77
Create Date: 2026-04-22 07:36:26.119278

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "fdca55926c40"
down_revision: Union[str, Sequence[str], None] = "02153a312b77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("pattern_code", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("datasets", "pattern_code")
