"""Add creation media and layout export tables.

Revision ID: 20261103_0015
Revises: 20261030_0014
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261103_0015"
down_revision: str | None = "20261030_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creation_media",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36)),
        sa.Column("asset_id", sa.String(length=36)),
        sa.Column("asset_version_id", sa.String(length=36)),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.String(length=64)),
        sa.Column("model", sa.String(length=120)),
        sa.Column("seed", sa.BigInteger()),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("mime", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trashed_at", sa.DateTime(timezone=True)),
        sa.Column("purge_after", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["asset_id"], ["creation_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["creation_asset_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["creation_projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_creation_media_user_created", "creation_media", ["user_id", "created_at"]
    )
    op.create_index("ix_creation_media_asset_kind", "creation_media", ["asset_id", "kind"])
    op.create_index("ix_creation_media_user_sha", "creation_media", ["user_id", "sha256"])
    op.create_index("ix_creation_media_purge_after", "creation_media", ["purge_after"])

    op.create_table(
        "creation_exports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("asset_version_id", sa.String(length=36)),
        sa.Column("target", sa.String(length=16), nullable=False),
        sa.Column("style_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("file_key", sa.String(length=512)),
        sa.Column("file_bytes", sa.BigInteger(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["asset_id"], ["creation_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["creation_asset_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_creation_exports_user_created", "creation_exports", ["user_id", "created_at"]
    )
    op.create_index("ix_creation_exports_asset", "creation_exports", ["asset_id"])
    op.create_index("ix_creation_exports_expires", "creation_exports", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_creation_exports_expires", table_name="creation_exports")
    op.drop_index("ix_creation_exports_asset", table_name="creation_exports")
    op.drop_index("ix_creation_exports_user_created", table_name="creation_exports")
    op.drop_table("creation_exports")
    op.drop_index("ix_creation_media_purge_after", table_name="creation_media")
    op.drop_index("ix_creation_media_user_sha", table_name="creation_media")
    op.drop_index("ix_creation_media_asset_kind", table_name="creation_media")
    op.drop_index("ix_creation_media_user_created", table_name="creation_media")
    op.drop_table("creation_media")
