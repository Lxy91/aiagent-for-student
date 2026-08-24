"""Add conversation pinning and archiving.

Revision ID: 20260824_0003
Revises: 20260822_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0003"
down_revision: str | None = "20260822_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "conversations",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_conversations_is_pinned", "conversations", ["is_pinned"])
    op.create_index("ix_conversations_is_archived", "conversations", ["is_archived"])


def downgrade() -> None:
    op.drop_index("ix_conversations_is_archived", table_name="conversations")
    op.drop_index("ix_conversations_is_pinned", table_name="conversations")
    op.drop_column("conversations", "is_archived")
    op.drop_column("conversations", "is_pinned")
