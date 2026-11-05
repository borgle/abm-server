from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ABM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    host: str = "0.0.0.0"
    port: int = Field(default=18050, ge=1, le=65535)
    database_url: str = "sqlite+aiosqlite:///./data/abm.db"
    public_base_url: str = ""
    oauth_issuer_url: str = ""
    oauth_access_token_ttl_seconds: int = Field(default=3600, ge=60)
    oauth_refresh_token_ttl_seconds: int = Field(default=30 * 24 * 60 * 60, ge=300)
    oauth_authorization_code_ttl_seconds: int = Field(default=300, ge=30)
    oauth_pending_ttl_seconds: int = Field(default=600, ge=60)
    forwarded_allow_ips: str = "127.0.0.1"
    extension_id: str = "cojffalolochaigkgngieopcefcgbcag"
    extension_github_url: str = "https://github.com/borgle/abm-extension"
    extension_release_url: str = "https://github.com/borgle/abm-extension/releases/latest"
    extension_store_url: str = ""
    session_cookie_secure: bool = True
    registration_require_approval: bool = True
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    social_login_enabled: bool = True
    social_login_state_ttl_seconds: int = Field(default=600, ge=60)
    social_google_client_id: str = ""
    social_google_client_secret: str = ""
    social_github_client_id: str = ""
    social_github_client_secret: str = ""
    social_microsoft_client_id: str = ""
    social_microsoft_client_secret: str = ""
    social_microsoft_tenant: str = "common"
    social_wechat_client_id: str = ""
    social_wechat_client_secret: str = ""
    social_qq_client_id: str = ""
    social_qq_client_secret: str = ""
    email_mode: str = "log"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "ABM <no-reply@localhost>"
    smtp_starttls: bool = True
    email_verification_ttl_seconds: int = 24 * 60 * 60
    password_reset_ttl_seconds: int = 60 * 60
    max_active_keys_free: int = Field(default=2, ge=1)
    max_active_keys_pro: int = Field(default=10, ge=1)
    quota_tool_calls_free: int = Field(default=1_000, ge=0)
    quota_tool_calls_pro: int = Field(default=20_000, ge=0)
    quota_video_bytes_free: int = Field(default=500 * 1024 * 1024, ge=0)
    quota_video_bytes_pro: int = Field(default=10 * 1024 * 1024 * 1024, ge=0)
    quota_video_jobs_free: int = Field(default=10, ge=0)
    quota_video_jobs_pro: int = Field(default=200, ge=0)
    quota_enforcement: str = "hard"
    alert_webhook_url: str = ""
    tool_timeout_ms: int = Field(default=300_000, ge=1)
    mcp_session_lease_ttl_seconds: int = Field(default=30 * 60, ge=60)
    extension_max_connections_per_key: int = Field(default=5, ge=1)
    extension_max_sessions_per_connection: int = Field(default=3, ge=1)
    extension_reserved_priority_slots: int = Field(default=1, ge=0)
    research_parallel_searches: int = Field(default=2, ge=1, le=5)
    research_pause_on_interstitial: bool = True
    research_attention_timeout_seconds: int = Field(default=300, ge=0)
    edition: str = "single"
    local_generations_per_day: int = Field(default=0, ge=0)
    local_tokens_per_month: int = Field(default=0, ge=0)
    local_images_per_day: int = Field(default=0, ge=0)
    local_image_max_n: int = Field(default=4, ge=1, le=4)
    local_storage_bytes: int = Field(default=0, ge=0)
    local_research_pages_per_month: int = Field(default=0, ge=0)
    local_browser_connections: int = Field(default=5, ge=1)
    local_browser_sessions: int = Field(default=3, ge=1)
    local_reserved_priority_slots: int = Field(default=1, ge=0)
    video_chunk_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    video_job_ttl_ms: int = Field(default=30 * 60 * 1000, ge=1)
    video_max_jobs_per_key: int = Field(default=2, ge=1)
    video_max_jobs_total: int = Field(default=20, ge=1)
    video_temp_dir: str = ""
    video_bridge_token_ttl_seconds: int = Field(default=3600, ge=60)
    max_video_bytes: int = Field(default=2 * 1024 * 1024 * 1024, ge=1)
    video_delivery: str = "auto"
    heartbeat_ms: int = Field(default=30_000, ge=1)
    stale_timeout_ms: int = Field(default=90_000, ge=1)
    hello_timeout_ms: int = Field(default=10_000, ge=1)
    log_level: str = "info"
    session_ttl_seconds: int = Field(default=7 * 24 * 60 * 60, ge=60)
    session_retention_days: int = Field(default=90, ge=1, le=3650)
    password_min_length: int = Field(default=10, ge=8)
    login_rate_limit_attempts: int = Field(default=5, ge=1)
    login_rate_limit_window_seconds: int = Field(default=15 * 60, ge=1)
    creation_secret_key: str = ""
    storage_backend: str = "local"
    media_root: str = "data/media"
    media_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    export_retention_days: int = Field(default=7, ge=1)
    s3_endpoint_url: str = ""
    s3_bucket: str = "abm-media"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "us-east-1"
    s3_prefix: str = "abm"
    s3_addressing_style: str = "path"
    s3_use_ssl: bool = False
    s3_auto_create_bucket: bool = True
    render_no_sandbox: bool = False

    def ensure_sqlite_directory(self) -> None:
        url = make_url(self.database_url)
        if not url.drivername.startswith("sqlite") or not url.database:
            return
        if url.database == ":memory:":
            return
        Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
