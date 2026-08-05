"""Initial schema: users, jobs, candidates, evaluations.

Revision ID: 0001
Revises:
Create Date: 2026-08-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGBLOB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("api_key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("jd_raw", sa.Text, nullable=False),
        sa.Column("jd_parsed", sa.JSON, nullable=True),
        sa.Column("weights", sa.JSON, nullable=True),
        sa.Column("thresholds", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("yoe", sa.Float, nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("resume_url", sa.String(1024), nullable=True),
        sa.Column("resume_text", sa.Text, nullable=True),
        sa.Column("parsed", sa.JSON, nullable=True),
        sa.Column(
            "embedding",
            sa.LargeBinary().with_variant(LONGBLOB, "mysql"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "processing", "done", "failed", name="candidatestatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("rubric", sa.JSON, nullable=True),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("verdict", sa.Enum("Fit", "Maybe", "Reject", name="verdict"), nullable=True),
        sa.Column("reasons", sa.JSON, nullable=True),
        sa.Column("model_used", sa.String(255), nullable=True),
        sa.Column("cache_key", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("evaluations")
    op.drop_table("candidates")
    op.drop_table("jobs")
    op.drop_table("users")
