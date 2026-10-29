"""Retain actionable summary failure messages."""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0015"
down_revision = "20261026_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_resumes", sa.Column("summary_error", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("user_resumes", "summary_error")
