"""Store a compact resume summary separately from the source."""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0013"
down_revision = "20261026_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_resumes", sa.Column("summary", sa.Text(), nullable=True))
    op.execute("UPDATE user_resumes SET summary = '' WHERE summary IS NULL")
    op.alter_column("user_resumes", "summary", existing_type=sa.Text(), nullable=False)


def downgrade():
    op.drop_column("user_resumes", "summary")
