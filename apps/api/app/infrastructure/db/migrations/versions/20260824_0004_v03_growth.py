"""Add V0.3 work materials, minutes, growth evidence, and progress reports.

Revision ID: 20260824_0004
Revises: 20260824_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0004"
down_revision: str | None = "20260824_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_materials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("material_type", sa.String(20), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("privacy_status", sa.String(30), nullable=False),
        sa.Column("content_excerpt", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_work_materials_user_id", "work_materials", ["user_id"])
    op.create_index("ix_work_materials_material_type", "work_materials", ["material_type"])
    op.create_index("ix_work_materials_status", "work_materials", ["status"])
    op.create_index("ix_work_materials_created_at", "work_materials", ["created_at"])
    op.create_table(
        "meeting_minutes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("source_material_id", sa.String(36), nullable=False, unique=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("action_items", sa.JSON(), nullable=False),
        sa.Column("pending_facts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_material_id"], ["work_materials.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_meeting_minutes_user_id", "meeting_minutes", ["user_id"])
    op.create_index(
        "ix_meeting_minutes_source_material_id", "meeting_minutes", ["source_material_id"]
    )
    op.create_table(
        "growth_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("summary", sa.String(1000), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("source_title", sa.String(255), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_growth_evidence_user_id", "growth_evidence", ["user_id"])
    op.create_index("ix_growth_evidence_capability", "growth_evidence", ["capability"])
    op.create_index("ix_growth_evidence_source_id", "growth_evidence", ["source_id"])
    op.create_index("ix_growth_evidence_user_created", "growth_evidence", ["user_id", "created_at"])
    op.create_table(
        "progress_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_progress_reports_user_id", "progress_reports", ["user_id"])
    op.create_index("ix_progress_reports_created_at", "progress_reports", ["created_at"])


def downgrade() -> None:
    op.drop_table("progress_reports")
    op.drop_table("growth_evidence")
    op.drop_table("meeting_minutes")
    op.drop_table("work_materials")
