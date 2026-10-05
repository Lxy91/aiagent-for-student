"""Store full extracted material text separately from its UI excerpt.

Revision ID: 20261005_0007
Revises: 20260824_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261005_0007"
down_revision: str | None = "20260824_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    extracted_type = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")
    op.add_column(
        "work_materials",
        sa.Column("extracted_text", extracted_type, nullable=True),
    )
    op.execute("UPDATE work_materials SET extracted_text = content_excerpt")
    op.alter_column(
        "work_materials",
        "extracted_text",
        existing_type=extracted_type,
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("work_materials", "extracted_text")
