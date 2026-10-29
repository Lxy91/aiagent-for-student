"""Add user resume with explicit context opt-in."""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0012"
down_revision = "20261007_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_resumes",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("user_resumes")
