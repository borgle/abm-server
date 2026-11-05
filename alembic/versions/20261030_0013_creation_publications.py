"""Add creation publication tasks for browser-assisted publishing.

Revision ID: 20261030_0013
Revises: 20261030_0012
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261030_0013"
down_revision: str | None = "20261030_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creation_publications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36)),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("target_url", sa.Text()),
        sa.Column("browser_session_id", sa.String(length=64)),
        sa.Column("connection_id", sa.String(length=64)),
        sa.Column("published_url", sa.Text()),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["creation_assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_creation_publications_user_created",
        "creation_publications",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_creation_publications_user_status",
        "creation_publications",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_creation_publications_user_status", table_name="creation_publications")
    op.drop_index("ix_creation_publications_user_created", table_name="creation_publications")
    op.drop_table("creation_publications")
