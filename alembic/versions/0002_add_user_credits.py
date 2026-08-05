"""Add users.credits — MVP billing (see app/api/billing.py).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("credits", sa.Integer, nullable=False, server_default="3"),
    )


def downgrade() -> None:
    op.drop_column("users", "credits")
