"""Store generated conversation artifacts for authenticated downloads.

Revision ID: 20260824_0006
Revises: 20260824_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260824_0006"
down_revision: str | None = "20260824_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    binary_type = sa.LargeBinary().with_variant(mysql.LONGBLOB(), "mysql")
    op.create_table(
        "generated_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("artifact_type", sa.String(20), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("binary_content", binary_type, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_generated_artifacts_user_id", "generated_artifacts", ["user_id"])
    op.create_index(
        "ix_generated_artifacts_conversation_id", "generated_artifacts", ["conversation_id"]
    )
    op.create_index(
        "ix_generated_artifacts_artifact_type", "generated_artifacts", ["artifact_type"]
    )
    op.create_index(
        "ix_generated_artifacts_created_at", "generated_artifacts", ["created_at"]
    )
    op.create_index(
        "ix_generated_artifacts_user_created",
        "generated_artifacts",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("generated_artifacts")
