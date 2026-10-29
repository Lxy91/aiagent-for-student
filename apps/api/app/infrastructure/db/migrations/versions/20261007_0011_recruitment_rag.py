"""Add normalized recruitment postings and RAG chunks.

Revision ID: 20261007_0011
Revises: 20261006_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261007_0011"
down_revision: str | None = "20261006_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_postings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(160), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("district", sa.String(120), nullable=False),
        sa.Column("education", sa.String(80), nullable=False),
        sa.Column("experience", sa.String(80), nullable=False),
        sa.Column("salary_text", sa.String(120), nullable=False),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("salary_months", sa.Integer(), nullable=True),
        sa.Column("requirements", sa.Text(), nullable=False),
        sa.Column("benefits", sa.JSON(), nullable=False),
        sa.Column("work_schedule", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("searchable_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ux_job_postings_source_external", "job_postings", ["source", "external_id"], unique=True
    )
    op.create_index("ix_job_postings_source", "job_postings", ["source"])
    op.create_index("ix_job_postings_title", "job_postings", ["title"])
    op.create_index("ix_job_postings_city", "job_postings", ["city"])
    op.create_index("ix_job_postings_education", "job_postings", ["education"])
    op.create_index("ix_job_postings_experience", "job_postings", ["experience"])
    op.create_index("ix_job_postings_content_hash", "job_postings", ["content_hash"])
    op.create_index("ix_job_postings_status", "job_postings", ["status"])
    op.create_index("ix_job_postings_city_status", "job_postings", ["city", "status"])
    op.create_index("ix_job_postings_last_seen", "job_postings", ["last_seen_at"])
    op.create_table(
        "job_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
    )
    op.create_index("ix_job_chunks_job_id", "job_chunks", ["job_id"])
    op.create_index("ux_job_chunks_job_ordinal", "job_chunks", ["job_id", "ordinal"], unique=True)


def downgrade() -> None:
    op.drop_table("job_chunks")
    op.drop_table("job_postings")
