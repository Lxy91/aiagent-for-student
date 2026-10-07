"""Persist the model-facing conversation context boundary.

Revision ID: 20261006_0009
Revises: 20261006_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261006_0009"
down_revision: str | None = "20261006_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("context_cleared_at", sa.DateTime(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column(
            "context_clear_notice_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "context_clear_notice_pending")
    op.drop_column("conversations", "context_cleared_at")
