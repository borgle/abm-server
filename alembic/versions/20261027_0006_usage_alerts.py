"""Add usage alert state.

Revision ID: 20261027_0006
Revises: 20261027_0005
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_0006"
down_revision: str | None = "20261027_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("api_key_id", sa.String(length=36), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "api_key_id",
            "month",
            "threshold",
            name="uq_usage_alerts_key_month_threshold",
        ),
    )
    op.create_index("ix_usage_alerts_user_month", "usage_alerts", ["user_id", "month"])


def downgrade() -> None:
    op.drop_index("ix_usage_alerts_user_month", table_name="usage_alerts")
    op.drop_table("usage_alerts")
