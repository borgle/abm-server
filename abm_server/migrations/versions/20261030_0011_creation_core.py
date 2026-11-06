"""Add creation projects, assets and versions.

Revision ID: 20261030_0011
Revises: 20261027_0010
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261030_0011"
down_revision: str | None = "20261027_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creation_projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "default_platform", sa.String(length=32), nullable=False, server_default="master"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_creation_projects_user_updated",
        "creation_projects",
        ["user_id", "archived_at", "updated_at"],
    )

    op.create_table(
        "creation_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36)),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="article"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("current_version_id", sa.String(length=36)),
        sa.Column("master_platform", sa.String(length=32), nullable=False, server_default="master"),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("trashed_at", sa.DateTime(timezone=True)),
        sa.Column("purge_after", sa.DateTime(timezone=True)),
        sa.Column("trash_reason", sa.String(length=32)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["creation_projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_creation_assets_user_status_updated",
        "creation_assets",
        ["user_id", "status", "updated_at"],
    )
    op.create_index("ix_creation_assets_project", "creation_assets", ["project_id"])
    op.create_index("ix_creation_assets_purge_after", "creation_assets", ["purge_after"])

    op.create_table(
        "creation_asset_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36)),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("outline", sa.JSON(), nullable=False),
        sa.Column("brief", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("model_source", sa.String(length=16)),
        sa.Column("model", sa.String(length=200)),
        sa.Column("prompt_version", sa.String(length=64)),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["creation_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "version_no", name="uq_creation_asset_versions_no"),
    )
    op.create_index(
        "ix_creation_asset_versions_asset",
        "creation_asset_versions",
        ["asset_id", "version_no"],
    )


def downgrade() -> None:
    op.drop_index("ix_creation_asset_versions_asset", table_name="creation_asset_versions")
    op.drop_table("creation_asset_versions")
    op.drop_index("ix_creation_assets_purge_after", table_name="creation_assets")
    op.drop_index("ix_creation_assets_project", table_name="creation_assets")
    op.drop_index("ix_creation_assets_user_status_updated", table_name="creation_assets")
    op.drop_table("creation_assets")
    op.drop_index("ix_creation_projects_user_updated", table_name="creation_projects")
    op.drop_table("creation_projects")
