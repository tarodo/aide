"""add_is_tech_to_fields

Revision ID: 02153a312b77
Revises: 712c37131a2c
Create Date: 2026-04-22 07:29:37.487375

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "02153a312b77"
down_revision: Union[str, Sequence[str], None] = "712c37131a2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fields",
        sa.Column(
            "is_tech",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("fields", "is_tech")
