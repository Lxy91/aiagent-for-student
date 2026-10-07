"""Store a separate model-facing sanitized message copy.

Revision ID: 20261006_0008
Revises: 20261005_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261006_0008"
down_revision: str | None = "20261005_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("sanitized_content", sa.Text(), nullable=True))
    op.execute("UPDATE messages SET sanitized_content = content")
    op.alter_column(
        "messages",
        "sanitized_content",
        existing_type=sa.Text(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("messages", "sanitized_content")
