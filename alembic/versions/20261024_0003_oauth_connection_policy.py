"""Add OAuth connection policy to codes and tokens.

Revision ID: 20261024_0003
Revises: 20261023_0002
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261024_0003"
down_revision: str | None = "20261023_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in (
        "oauth_authorization_codes",
        "oauth_access_tokens",
        "oauth_refresh_tokens",
    ):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "connection_mode",
                    sa.String(length=16),
                    nullable=False,
                    server_default="auto",
                )
            )
            batch.add_column(
                sa.Column(
                    "connection_ids",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                )
            )


def downgrade() -> None:
    for table in (
        "oauth_authorization_codes",
        "oauth_access_tokens",
        "oauth_refresh_tokens",
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("connection_ids")
            batch.drop_column("connection_mode")
