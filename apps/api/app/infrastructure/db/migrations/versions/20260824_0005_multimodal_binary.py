"""Store image attachments for multimodal model routing.

Revision ID: 20260824_0005
Revises: 20260824_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260824_0005"
down_revision: str | None = "20260824_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    binary_type = sa.LargeBinary().with_variant(mysql.LONGBLOB(), "mysql")
    op.add_column("work_materials", sa.Column("binary_content", binary_type, nullable=True))


def downgrade() -> None:
    op.drop_column("work_materials", "binary_content")
