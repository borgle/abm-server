"""Add social registration completion for providers without email.

Revision ID: 20261027_0010
Revises: 20261027_0009
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_0010"
down_revision: str | None = "20261027_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_pending_registrations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("avatar_url", sa.String(length=500)),
        sa.Column("next_path", sa.String(length=500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_social_pending_registrations_token_hash",
        ),
    )
    op.create_index(
        "ix_social_pending_registrations_expires_at",
        "social_pending_registrations",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_social_pending_registrations_expires_at",
        table_name="social_pending_registrations",
    )
    op.drop_table("social_pending_registrations")
