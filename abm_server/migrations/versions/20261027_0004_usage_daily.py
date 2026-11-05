"""Add daily usage counters.

Revision ID: 20261027_0004
Revises: 20261024_0003
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_0004"
down_revision: str | None = "20261024_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_daily",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("api_key_id", sa.String(length=36), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("video_jobs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("video_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key_id", "day", name="uq_usage_daily_key_day"),
    )
    op.create_index("ix_usage_daily_user_day", "usage_daily", ["user_id", "day"])


def downgrade() -> None:
    op.drop_index("ix_usage_daily_user_day", table_name="usage_daily")
    op.drop_table("usage_daily")
