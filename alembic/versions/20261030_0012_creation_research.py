"""Add creation research jobs, events and sources.

Revision ID: 20261030_0012
Revises: 20261030_0011
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261030_0012"
down_revision: str | None = "20261030_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creation_research_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36)),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("exclusions", sa.JSON(), nullable=False),
        sa.Column("engines", sa.JSON(), nullable=False),
        sa.Column("depth", sa.String(length=16), nullable=False, server_default="standard"),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="zh"),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("total_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_collected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("attention", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["creation_projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_creation_research_jobs_user_created",
        "creation_research_jobs",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_creation_research_jobs_user_status",
        "creation_research_jobs",
        ["user_id", "status"],
    )

    op.create_table(
        "creation_job_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["job_id"], ["creation_research_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "seq", name="uq_creation_job_events_seq"),
    )
    op.create_index("ix_creation_job_events_job_seq", "creation_job_events", ["job_id", "seq"])

    op.create_table(
        "creation_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36)),
        sa.Column("project_id", sa.String(length=36)),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("author", sa.String(length=255)),
        sa.Column("published_at", sa.String(length=64)),
        sa.Column("language", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="article"),
        sa.Column("engine", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fingerprint", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("credibility", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("trashed_at", sa.DateTime(timezone=True)),
        sa.Column("purge_after", sa.DateTime(timezone=True)),
        sa.Column("trash_reason", sa.String(length=32)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["creation_research_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["creation_projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "canonical_url", name="uq_creation_sources_user_url"),
    )
    op.create_index(
        "ix_creation_sources_user_trash_fetched",
        "creation_sources",
        ["user_id", "trashed_at", "fetched_at"],
    )
    op.create_index("ix_creation_sources_job", "creation_sources", ["job_id"])
    op.create_index("ix_creation_sources_purge_after", "creation_sources", ["purge_after"])
    op.create_index("ix_creation_sources_domain", "creation_sources", ["user_id", "domain"])


def downgrade() -> None:
    op.drop_index("ix_creation_sources_domain", table_name="creation_sources")
    op.drop_index("ix_creation_sources_purge_after", table_name="creation_sources")
    op.drop_index("ix_creation_sources_job", table_name="creation_sources")
    op.drop_index("ix_creation_sources_user_trash_fetched", table_name="creation_sources")
    op.drop_table("creation_sources")
    op.drop_index("ix_creation_job_events_job_seq", table_name="creation_job_events")
    op.drop_table("creation_job_events")
    op.drop_index("ix_creation_research_jobs_user_status", table_name="creation_research_jobs")
    op.drop_index("ix_creation_research_jobs_user_created", table_name="creation_research_jobs")
    op.drop_table("creation_research_jobs")
