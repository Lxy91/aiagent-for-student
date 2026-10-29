"""Invalidate heuristic summaries for semantic extraction."""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0014"
down_revision = "20261026_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_resumes",
        sa.Column("summary_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("UPDATE user_resumes SET summary = ''")


def downgrade():
    op.drop_column("user_resumes", "summary_version")
