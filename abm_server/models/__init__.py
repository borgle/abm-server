from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"
    DISABLED = "disabled"


class PlanCode(StrEnum):
    FREE = "free"
    PRO = "pro"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    application_note: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default=UserRole.USER, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=UserStatus.PENDING, nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text)
    plan_code: Mapped[str] = mapped_column(String(16), default=PlanCode.FREE, nullable=False)
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )

    sessions: Mapped[list[AccountSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="ApiKey.user_id",
    )


class AccountSession(Base):
    __tablename__ = "account_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_account_sessions_token_hash"),
        Index("ix_account_sessions_user_revoked", "user_id", "revoked_at"),
        Index("ix_account_sessions_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="sessions")


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("public_prefix", name="uq_api_keys_public_prefix"),
        UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        Index("ix_api_keys_user_revoked", "user_id", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    public_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )

    user: Mapped[User] = relationship(
        back_populates="api_keys",
        foreign_keys=[user_id],
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )


class AccountAuditEvent(Base):
    __tablename__ = "account_audit_events"
    __table_args__ = (
        Index("ix_account_audit_subject_created", "subject_user_id", "created_at"),
        Index("ix_account_audit_key_created", "api_key_id", "created_at"),
        Index("ix_account_audit_event_type", "event_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    subject_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    api_key_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthClient(Base):
    __tablename__ = "oauth_clients"
    __table_args__ = (Index("ix_oauth_clients_created_at", "created_at"),)

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_name: Mapped[str | None] = mapped_column(String(200))
    client_uri: Mapped[str | None] = mapped_column(String(500))
    logo_uri: Mapped[str | None] = mapped_column(String(500))
    redirect_uris: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    grant_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    response_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    scope: Mapped[str | None] = mapped_column(Text)
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(32), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthPendingAuthorization(Base):
    __tablename__ = "oauth_pending_authorizations"
    __table_args__ = (Index("ix_oauth_pending_expires_at", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    state: Mapped[str | None] = mapped_column(Text)
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthAuthorizationCode(Base):
    __tablename__ = "oauth_authorization_codes"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_oauth_authorization_codes_code_hash"),
        Index("ix_oauth_authorization_codes_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    connection_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    connection_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthAccessToken(Base):
    __tablename__ = "oauth_access_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_oauth_access_tokens_token_hash"),
        Index("ix_oauth_access_tokens_user_revoked", "user_id", "revoked_at"),
        Index("ix_oauth_access_tokens_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    connection_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    connection_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthRefreshToken(Base):
    __tablename__ = "oauth_refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_oauth_refresh_tokens_token_hash"),
        Index("ix_oauth_refresh_tokens_user_revoked", "user_id", "revoked_at"),
        Index("ix_oauth_refresh_tokens_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    connection_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    connection_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    __table_args__ = (
        UniqueConstraint("api_key_id", "day", name="uq_usage_daily_key_day"),
        Index("ix_usage_daily_user_day", "user_id", "day"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AccountToken(Base):
    __tablename__ = "account_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_account_tokens_token_hash"),
        Index("ix_account_tokens_user_purpose", "user_id", "purpose"),
        Index("ix_account_tokens_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageAlert(Base):
    __tablename__ = "usage_alerts"
    __table_args__ = (
        UniqueConstraint(
            "api_key_id", "month", "threshold", name="uq_usage_alerts_key_month_threshold"
        ),
        Index("ix_usage_alerts_user_month", "user_id", "month"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountNotice(Base):
    __tablename__ = "account_notices"
    __table_args__ = (Index("ix_account_notices_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    action_url: Mapped[str | None] = mapped_column(String(500))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_external_identities_provider_subject"),
        Index("ix_external_identities_user", "user_id"),
        Index("ix_external_identities_provider_email", "provider", "email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class SocialLoginState(Base):
    __tablename__ = "social_login_states"
    __table_args__ = (
        UniqueConstraint("state_hash", name="uq_social_login_states_state_hash"),
        Index("ix_social_login_states_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    browser_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    next_path: Mapped[str] = mapped_column(String(500), nullable=False, default="/console")
    link_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SocialPendingRegistration(Base):
    __tablename__ = "social_pending_registrations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_social_pending_registrations_token_hash"),
        Index("ix_social_pending_registrations_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    browser_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    next_path: Mapped[str] = mapped_column(String(500), nullable=False, default="/console")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreationProject(Base):
    __tablename__ = "creation_projects"
    __table_args__ = (
        Index("ix_creation_projects_user_updated", "user_id", "archived_at", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_platform: Mapped[str] = mapped_column(String(32), default="master", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreationAsset(Base):
    __tablename__ = "creation_assets"
    __table_args__ = (
        Index("ix_creation_assets_user_status_updated", "user_id", "status", "updated_at"),
        Index("ix_creation_assets_project", "project_id"),
        Index("ix_creation_assets_purge_after", "purge_after"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("creation_projects.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="article", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(36))
    master_platform: Mapped[str] = mapped_column(String(32), default="master", nullable=False)
    tags: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trash_reason: Mapped[str | None] = mapped_column(String(32))


class CreationAssetVersion(Base):
    __tablename__ = "creation_asset_versions"
    __table_args__ = (
        UniqueConstraint("asset_id", "version_no", name="uq_creation_asset_versions_no"),
        Index("ix_creation_asset_versions_asset", "asset_id", "version_no"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("creation_assets.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(String(36))
    content_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    outline: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    brief: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)
    citations: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    source_ids: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    model_source: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreationResearchJob(Base):
    __tablename__ = "creation_research_jobs"
    __table_args__ = (
        Index("ix_creation_research_jobs_user_created", "user_id", "created_at"),
        Index("ix_creation_research_jobs_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("creation_projects.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    keywords: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    exclusions: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    engines: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    depth: Mapped[str] = mapped_column(String(16), default="standard", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="zh", nullable=False)
    plan: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    progress: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)
    total_queries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_queries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_collected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    attention: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreationJobEvent(Base):
    __tablename__ = "creation_job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "seq", name="uq_creation_job_events_seq"),
        Index("ix_creation_job_events_job_seq", "job_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("creation_research_jobs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreationSource(Base):
    __tablename__ = "creation_sources"
    __table_args__ = (
        UniqueConstraint("user_id", "canonical_url", name="uq_creation_sources_user_url"),
        Index("ix_creation_sources_user_trash_fetched", "user_id", "trashed_at", "fetched_at"),
        Index("ix_creation_sources_job", "job_id"),
        Index("ix_creation_sources_purge_after", "purge_after"),
        Index("ix_creation_sources_domain", "user_id", "domain"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("creation_research_jobs.id", ondelete="SET NULL")
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("creation_projects.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    author: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="article", nullable=False)
    engine: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    credibility: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    factors: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)
    metrics: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)
    tags: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trash_reason: Mapped[str | None] = mapped_column(String(32))


class CreationPublication(Base):
    __tablename__ = "creation_publications"
    __table_args__ = (
        Index("ix_creation_publications_user_created", "user_id", "created_at"),
        Index("ix_creation_publications_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("creation_assets.id", ondelete="SET NULL")
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    target_url: Mapped[str | None] = mapped_column(Text)
    browser_session_id: Mapped[str | None] = mapped_column(String(64))
    connection_id: Mapped[str | None] = mapped_column(String(64))
    published_url: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemConfig(Base):
    __tablename__ = "system_configs"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    group: Mapped[str] = mapped_column(String(40), default="general", nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )


class CreationMedia(Base):
    """Generated or uploaded image/video attached to a creation asset version."""

    __tablename__ = "creation_media"
    __table_args__ = (
        Index("ix_creation_media_user_created", "user_id", "created_at"),
        Index("ix_creation_media_asset_kind", "asset_id", "kind"),
        Index("ix_creation_media_user_sha", "user_id", "sha256"),
        Index("ix_creation_media_purge_after", "purge_after"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("creation_projects.id", ondelete="SET NULL")
    )
    asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("creation_assets.id", ondelete="CASCADE")
    )
    asset_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("creation_asset_versions.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16), default="inline", nullable=False)
    platform: Mapped[str] = mapped_column(String(32), default="master", nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="generated", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ready", nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(120))
    seed: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mime: Mapped[str] = mapped_column(String(64), default="image/png", nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    meta: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreationExport(Base):
    """Rendered layout export (WeChat HTML or Xiaohongshu card set)."""

    __tablename__ = "creation_exports"
    __table_args__ = (
        Index("ix_creation_exports_user_created", "user_id", "created_at"),
        Index("ix_creation_exports_asset", "asset_id"),
        Index("ix_creation_exports_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("creation_assets.id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("creation_asset_versions.id", ondelete="SET NULL")
    )
    target: Mapped[str] = mapped_column(String(16), nullable=False)
    style_id: Mapped[str] = mapped_column(String(32), default="default", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    options: Mapped[Any] = mapped_column(JSON, default=dict, nullable=False)
    file_key: Mapped[str | None] = mapped_column(String(512))
    file_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    files: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

