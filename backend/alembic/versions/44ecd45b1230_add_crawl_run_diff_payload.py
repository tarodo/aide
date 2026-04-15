"""add_crawl_run_diff_payload

Revision ID: 44ecd45b1230
Revises: 85e55c3a1a5f
Create Date: 2026-04-14 16:53:07.293531

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "44ecd45b1230"
down_revision: Union[str, Sequence[str], None] = "85e55c3a1a5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "crawl_runs",
        sa.Column(
            "diff_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("crawl_runs", "diff_payload")
