"""Add candidates.updated_at + stale_retries — support the stale-candidate watchdog.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.add_column(
        "candidates",
        sa.Column("stale_retries", sa.Integer, server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("candidates", "stale_retries")
    op.drop_column("candidates", "updated_at")
