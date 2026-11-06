"""Add social login identities and state.

Revision ID: 20261027_0008
Revises: 20261027_0007
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261027_0008"
down_revision: str | None = "20261027_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("display_name", sa.String(length=120)),
        sa.Column("avatar_url", sa.String(length=500)),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "subject",
            name="uq_external_identities_provider_subject",
        ),
    )
    op.create_index("ix_external_identities_user", "external_identities", ["user_id"])
    op.create_index(
        "ix_external_identities_provider_email",
        "external_identities",
        ["provider", "email"],
    )

    op.create_table(
        "social_login_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("next_path", sa.String(length=500), nullable=False),
        sa.Column("link_user_id", sa.String(length=36)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["link_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash", name="uq_social_login_states_state_hash"),
    )
    op.create_index(
        "ix_social_login_states_expires_at",
        "social_login_states",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_social_login_states_expires_at", table_name="social_login_states")
    op.drop_table("social_login_states")
    op.drop_index("ix_external_identities_provider_email", table_name="external_identities")
    op.drop_index("ix_external_identities_user", table_name="external_identities")
    op.drop_table("external_identities")
