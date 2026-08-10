"""Add jobs.jd_parse_pending — non-blocking JD parse fallback when the LLM is down.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("jd_parse_pending", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("jobs", "jd_parse_pending")
