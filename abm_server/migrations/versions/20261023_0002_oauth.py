"""Add OAuth clients, authorization requests, codes, and tokens.

Revision ID: 20261023_0002
Revises: 20261019_0001
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_0002"
down_revision: str | None = "20261019_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=True),
        sa.Column("client_uri", sa.String(length=500), nullable=True),
        sa.Column("logo_uri", sa.String(length=500), nullable=True),
        sa.Column("redirect_uris", sa.JSON(), nullable=False),
        sa.Column("grant_types", sa.JSON(), nullable=False),
        sa.Column("response_types", sa.JSON(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column(
            "token_endpoint_auth_method",
            sa.String(length=32),
            nullable=False,
            server_default="none",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("client_id"),
    )
    op.create_index(
        "ix_oauth_clients_created_at",
        "oauth_clients",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "oauth_pending_authorizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_oauth_pending_expires_at",
        "oauth_pending_authorizations",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "code_hash",
            name="uq_oauth_authorization_codes_code_hash",
        ),
    )
    op.create_index(
        "ix_oauth_authorization_codes_expires_at",
        "oauth_authorization_codes",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "oauth_access_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_oauth_access_tokens_token_hash"),
    )
    op.create_index(
        "ix_oauth_access_tokens_user_revoked",
        "oauth_access_tokens",
        ["user_id", "revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_oauth_access_tokens_expires_at",
        "oauth_access_tokens",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_oauth_refresh_tokens_token_hash"),
    )
    op.create_index(
        "ix_oauth_refresh_tokens_user_revoked",
        "oauth_refresh_tokens",
        ["user_id", "revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_oauth_refresh_tokens_expires_at",
        "oauth_refresh_tokens",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_refresh_tokens_expires_at", table_name="oauth_refresh_tokens")
    op.drop_index("ix_oauth_refresh_tokens_user_revoked", table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_index("ix_oauth_access_tokens_expires_at", table_name="oauth_access_tokens")
    op.drop_index("ix_oauth_access_tokens_user_revoked", table_name="oauth_access_tokens")
    op.drop_table("oauth_access_tokens")
    op.drop_index(
        "ix_oauth_authorization_codes_expires_at",
        table_name="oauth_authorization_codes",
    )
    op.drop_table("oauth_authorization_codes")
    op.drop_index("ix_oauth_pending_expires_at", table_name="oauth_pending_authorizations")
    op.drop_table("oauth_pending_authorizations")
    op.drop_index("ix_oauth_clients_created_at", table_name="oauth_clients")
    op.drop_table("oauth_clients")
