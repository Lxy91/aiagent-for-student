"""Add V0.2 tool execution, connectors, reminders, and jobs.

Revision ID: 20260822_0002
Revises: 20260820_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.execute(sa.text("UPDATE messages SET metadata_json = '{}' WHERE metadata_json IS NULL"))
    op.alter_column("messages", "metadata_json", existing_type=sa.JSON(), nullable=False)
    op.create_table(
        "external_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("token_hint", sa.String(20), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_external_connections_user_id", "external_connections", ["user_id"])
    op.create_index(
        "ix_external_connections_user_provider",
        "external_connections",
        ["user_id", "provider"],
        unique=True,
    )
    op.create_table(
        "tool_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(40), nullable=True),
        sa.Column("effect", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tool_actions_user_id", "tool_actions", ["user_id"])
    op.create_index("ix_tool_actions_task_id", "tool_actions", ["task_id"])
    op.create_table(
        "reminders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("remind_at", sa.DateTime(), nullable=False),
        sa.Column("timezone", sa.String(60), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_reminders_user_id", "reminders", ["user_id"])
    op.create_index("ix_reminders_task_id", "reminders", ["task_id"])
    op.create_index("ix_reminders_remind_at", "reminders", ["remind_at"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.String(1000), nullable=False),
        sa.Column("source_key", sa.String(120), nullable=False, unique=True),
        sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_background_jobs_user_id", "background_jobs", ["user_id"])
    op.create_index("ix_background_jobs_job_type", "background_jobs", ["job_type"])
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])
    op.create_index("ix_background_jobs_next_run_at", "background_jobs", ["next_run_at"])
    op.create_table(
        "tool_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("tool_version", sa.String(20), nullable=False),
        sa.Column("effect", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("output_summary", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tool_runs_trace_id", "tool_runs", ["trace_id"])
    op.create_index("ix_tool_runs_user_id", "tool_runs", ["user_id"])
    op.create_index("ix_tool_runs_tool_name", "tool_runs", ["tool_name"])
    op.create_index("ix_tool_runs_status", "tool_runs", ["status"])
    op.create_index("ix_tool_runs_user_created", "tool_runs", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("tool_runs")
    op.drop_table("background_jobs")
    op.drop_table("notifications")
    op.drop_table("reminders")
    op.drop_table("tool_actions")
    op.drop_table("external_connections")
    op.drop_column("messages", "metadata_json")
