"""Store compressed conversation context summaries.

Revision ID: 20261006_0010
Revises: 20261006_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261006_0010"
down_revision: str | None = "20261006_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("context_summary", sa.Text(), nullable=True),
    )
    op.execute("UPDATE conversations SET context_summary = '' WHERE context_summary IS NULL")
    op.alter_column(
        "conversations",
        "context_summary",
        existing_type=sa.Text(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("conversations", "context_summary")
