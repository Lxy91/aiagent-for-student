"""Preserve original resume attachments."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGBLOB

revision = "20261026_0016"
down_revision = "20261026_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_resumes", sa.Column("attachment_size", sa.Integer(), nullable=True))
    op.add_column(
        "user_resumes",
        sa.Column(
            "binary_content", sa.LargeBinary().with_variant(LONGBLOB(), "mysql"), nullable=True
        ),
    )


def downgrade():
    op.drop_column("user_resumes", "binary_content")
    op.drop_column("user_resumes", "attachment_size")
