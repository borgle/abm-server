"""Editable runtime configuration with grouped definitions and import/export."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import record_audit
from .config import Settings
from .errors import ApiError
from .models import SystemConfig, User

CONFIG_EVENT = "ABM_ADMIN_SYSTEM_CONFIG_UPDATED"
CONFIG_VERSION = 1


@dataclass(frozen=True, slots=True)
class ConfigSpec:
    key: str
    group: str
    label: str
    description: str = ""
    type: str = "int"
    minimum: int | None = None
    maximum: int | None = None
    options: tuple[str, ...] = ()
    restart_required: bool = False


GROUPS: tuple[dict[str, str], ...] = (
    {"id": "accounts", "label": "账号与会话"},
    {"id": "quotas", "label": "配额与用量"},
    {"id": "browser", "label": "浏览器与 MCP"},
    {"id": "video", "label": "视频中转"},
    {"id": "oauth", "label": "登录与 OAuth"},
    {"id": "email", "label": "邮件通知"},
)

SPECS: tuple[ConfigSpec, ...] = (
    ConfigSpec(
        "password_min_length", "accounts", "密码最小长度", "新密码至少包含的字符数。", "int", 8, 128
    ),
    ConfigSpec(
        "session_ttl_seconds",
        "accounts",
        "会话有效期",
        "账号会话的绝对有效期（秒）。",
        "int",
        60,
        31_536_000,
    ),
    ConfigSpec(
        "max_active_keys_free",
        "accounts",
        "Free Key 上限",
        "Free 套餐可同时有效的 API Key 数量。",
        "int",
        1,
        100,
    ),
    ConfigSpec(
        "max_active_keys_pro",
        "accounts",
        "Pro Key 上限",
        "Pro 套餐可同时有效的 API Key 数量。",
        "int",
        1,
        1000,
    ),
    ConfigSpec(
        "login_rate_limit_attempts",
        "accounts",
        "登录尝试次数",
        "时间窗口内允许的登录尝试次数。",
        "int",
        1,
        1000,
    ),
    ConfigSpec(
        "login_rate_limit_window_seconds",
        "accounts",
        "登录限流窗口",
        "登录限流时间窗口（秒）。",
        "int",
        60,
        86_400,
    ),
    ConfigSpec(
        "quota_tool_calls_free",
        "quotas",
        "Free 工具调用",
        "Free 套餐每月工具调用额度。",
        "int",
        0,
        10_000_000,
    ),
    ConfigSpec(
        "quota_tool_calls_pro",
        "quotas",
        "Pro 工具调用",
        "Pro 套餐每月工具调用额度。",
        "int",
        0,
        100_000_000,
    ),
    ConfigSpec(
        "quota_video_bytes_free",
        "quotas",
        "Free 视频字节",
        "Free 套餐每月视频中转字节数。",
        "int",
        0,
        10**13,
    ),
    ConfigSpec(
        "quota_video_bytes_pro",
        "quotas",
        "Pro 视频字节",
        "Pro 套餐每月视频中转字节数。",
        "int",
        0,
        10**13,
    ),
    ConfigSpec(
        "quota_video_jobs_free",
        "quotas",
        "Free 视频作业",
        "Free 套餐每月视频作业数。",
        "int",
        0,
        10_000,
    ),
    ConfigSpec(
        "quota_video_jobs_pro",
        "quotas",
        "Pro 视频作业",
        "Pro 套餐每月视频作业数。",
        "int",
        0,
        100_000,
    ),
    ConfigSpec(
        "quota_enforcement",
        "quotas",
        "额度执行方式",
        "hard 拒绝超额；soft 只提醒。",
        "str",
        options=("hard", "soft"),
    ),
    ConfigSpec(
        "alert_webhook_url", "quotas", "额度告警 Webhook", "达到额度阈值时发送 POST 的地址。", "str"
    ),
    ConfigSpec(
        "tool_timeout_ms",
        "browser",
        "工具超时",
        "单个浏览器工具调用的默认超时（毫秒）。",
        "int",
        1000,
        3_600_000,
    ),
    ConfigSpec(
        "mcp_session_lease_ttl_seconds",
        "browser",
        "MCP 租约 TTL",
        "浏览器会话租约有效期（秒）。",
        "int",
        60,
        86_400,
    ),
    ConfigSpec(
        "extension_max_connections_per_key",
        "browser",
        "每 Key 连接数",
        "同一 API Key 可同时在线的浏览器数。",
        "int",
        1,
        50,
    ),
    ConfigSpec(
        "extension_max_sessions_per_connection",
        "browser",
        "每连接会话数",
        "同一浏览器可并行的任务组数。",
        "int",
        1,
        20,
    ),
    ConfigSpec(
        "extension_reserved_priority_slots",
        "browser",
        "发布预留位",
        "为发布任务保留的高优先级会话位。",
        "int",
        0,
        10,
    ),
    ConfigSpec(
        "heartbeat_ms",
        "browser",
        "心跳间隔",
        "服务端发送 ping 的间隔（毫秒）。",
        "int",
        1000,
        300_000,
        restart_required=True,
    ),
    ConfigSpec(
        "stale_timeout_ms",
        "browser",
        "连接超时",
        "无活动多久后关闭连接（毫秒）。",
        "int",
        5000,
        3_600_000,
        restart_required=True,
    ),
    ConfigSpec(
        "hello_timeout_ms",
        "browser",
        "握手超时",
        "等待 session.hello 的时间（毫秒）。",
        "int",
        1000,
        300_000,
        restart_required=True,
    ),
    ConfigSpec(
        "video_chunk_bytes",
        "video",
        "视频分片大小",
        "每个中转分片的字节数。",
        "int",
        1024,
        100 * 1024 * 1024,
        restart_required=True,
    ),
    ConfigSpec(
        "video_job_ttl_ms",
        "video",
        "视频作业 TTL",
        "未完成视频作业的保留时间（毫秒）。",
        "int",
        60_000,
        86_400_000,
    ),
    ConfigSpec(
        "video_max_jobs_per_key",
        "video",
        "每 Key 视频作业",
        "每个 API Key 同时进行的视频作业上限。",
        "int",
        1,
        100,
    ),
    ConfigSpec(
        "video_max_jobs_total",
        "video",
        "全局视频作业",
        "服务端同时进行的视频作业上限。",
        "int",
        1,
        1000,
    ),
    ConfigSpec(
        "video_bridge_token_ttl_seconds",
        "video",
        "桥接令牌 TTL",
        "视频桥令牌有效期（秒）。",
        "int",
        60,
        86_400,
    ),
    ConfigSpec(
        "max_video_bytes",
        "video",
        "视频大小上限",
        "单个视频允许的最大字节数。",
        "int",
        1024,
        10**12,
    ),
    ConfigSpec(
        "video_delivery",
        "video",
        "视频投递方式",
        "bridge / url / auto。",
        "str",
        options=("bridge", "url", "auto"),
    ),
    ConfigSpec("video_temp_dir", "video", "视频临时目录", "留空使用系统临时目录。", "str"),
    ConfigSpec(
        "oauth_access_token_ttl_seconds",
        "oauth",
        "Access Token TTL",
        "OAuth access token 有效期（秒）。",
        "int",
        60,
        86_400,
    ),
    ConfigSpec(
        "oauth_refresh_token_ttl_seconds",
        "oauth",
        "Refresh Token TTL",
        "OAuth refresh token 有效期（秒）。",
        "int",
        300,
        31_536_000,
    ),
    ConfigSpec(
        "oauth_authorization_code_ttl_seconds",
        "oauth",
        "授权码 TTL",
        "OAuth authorization code 有效期（秒）。",
        "int",
        30,
        3600,
    ),
    ConfigSpec(
        "oauth_pending_ttl_seconds",
        "oauth",
        "授权请求 TTL",
        "待确认授权请求的有效期（秒）。",
        "int",
        60,
        86_400,
    ),
    ConfigSpec(
        "social_login_enabled", "oauth", "启用第三方登录", "关闭后隐藏第三方登录入口。", "bool"
    ),
    ConfigSpec(
        "social_login_state_ttl_seconds",
        "oauth",
        "第三方登录 state TTL",
        "state 参数有效期（秒）。",
        "int",
        60,
        3600,
    ),
    ConfigSpec(
        "email_mode",
        "email",
        "邮件发送方式",
        "log 只写日志；smtp 使用下方配置。",
        "str",
        options=("log", "smtp"),
    ),
    ConfigSpec("smtp_host", "email", "SMTP 主机", "SMTP 服务器地址。", "str"),
    ConfigSpec("smtp_port", "email", "SMTP 端口", "SMTP 端口。", "int", 1, 65535),
    ConfigSpec("smtp_username", "email", "SMTP 用户名", "SMTP 登录用户名。", "str"),
    ConfigSpec("smtp_from", "email", "发件人", "例如 ABM <no-reply@example.com>。", "str"),
    ConfigSpec("smtp_starttls", "email", "SMTP STARTTLS", "是否启用 STARTTLS。", "bool"),
    ConfigSpec(
        "email_verification_ttl_seconds",
        "email",
        "验证邮件 TTL",
        "邮箱验证链接有效期（秒）。",
        "int",
        300,
        604_800,
    ),
    ConfigSpec(
        "password_reset_ttl_seconds",
        "email",
        "重置邮件 TTL",
        "密码重置链接有效期（秒）。",
        "int",
        300,
        604_800,
    ),
)

SPEC_BY_KEY = {spec.key: spec for spec in SPECS}


def default_for(key: str) -> Any:
    field = Settings.model_fields[key]
    return field.default


def _coerce(spec: ConfigSpec, value: Any) -> Any:
    if spec.type == "bool":
        if not isinstance(value, bool):
            raise ApiError(422, "ABM_VALIDATION_ERROR", f"{spec.key} must be a boolean.")
        return value
    if spec.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError(422, "ABM_VALIDATION_ERROR", f"{spec.key} must be an integer.")
        if spec.minimum is not None and value < spec.minimum:
            raise ApiError(422, "ABM_VALIDATION_ERROR", f"{spec.key} is below the minimum.")
        if spec.maximum is not None and value > spec.maximum:
            raise ApiError(422, "ABM_VALIDATION_ERROR", f"{spec.key} exceeds the maximum.")
        return value
    if not isinstance(value, str):
        raise ApiError(422, "ABM_VALIDATION_ERROR", f"{spec.key} must be a string.")
    if spec.options and value not in spec.options:
        raise ApiError(422, "ABM_VALIDATION_ERROR", f"{spec.key} has an invalid value.")
    return value[:2000]


def validate_values(values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise ApiError(422, "ABM_VALIDATION_ERROR", "values must be an object.")
    unknown = [key for key in values if key not in SPEC_BY_KEY]
    if unknown:
        raise ApiError(
            422,
            "ABM_VALIDATION_ERROR",
            f"Unknown configuration key: {unknown[0]}.",
        )
    return {key: _coerce(SPEC_BY_KEY[key], value) for key, value in values.items()}


async def load_overrides(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.scalars(select(SystemConfig))).all()
    return {row.key: row.value for row in rows if row.key in SPEC_BY_KEY}


def capture_base(settings: Settings) -> dict[str, Any]:
    return {spec.key: getattr(settings, spec.key) for spec in SPECS}


def apply_overrides(
    settings: Settings,
    overrides: dict[str, Any],
    base: dict[str, Any] | None = None,
) -> None:
    clean = validate_values(overrides)
    if base is not None:
        for key, value in base.items():
            if key in SPEC_BY_KEY:
                setattr(settings, key, value)
    for key, value in clean.items():
        setattr(settings, key, value)


def config_payload(
    settings: Settings,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    groups = []
    for group in GROUPS:
        items = []
        for spec in SPECS:
            if spec.group != group["id"]:
                continue
            value = overrides.get(spec.key, getattr(settings, spec.key))
            items.append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "description": spec.description,
                    "type": spec.type,
                    "value": value,
                    "default": default_for(spec.key),
                    "minimum": spec.minimum,
                    "maximum": spec.maximum,
                    "options": list(spec.options),
                    "restartRequired": spec.restart_required,
                    "source": "database" if spec.key in overrides else "default",
                }
            )
        groups.append({**group, "items": items})
    return {
        "version": CONFIG_VERSION,
        "groups": groups,
        "updatedAt": datetime.now(UTC).isoformat(),
    }


async def save_overrides(
    session: AsyncSession,
    settings: Settings,
    user: User,
    values: dict[str, Any],
    *,
    replace: bool = False,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean = validate_values(values)
    existing = {row.key: row for row in (await session.scalars(select(SystemConfig))).all()}
    changes: dict[str, dict[str, Any]] = {}
    for key, value in clean.items():
        before = existing[key].value if key in existing else getattr(settings, key)
        if before != value:
            changes[key] = {"before": before, "after": value}
        row = existing.get(key)
        if row is None:
            session.add(
                SystemConfig(key=key, group=SPEC_BY_KEY[key].group, value=value, updated_by=user.id)
            )
        else:
            row.value = value
            row.group = SPEC_BY_KEY[key].group
            row.updated_by = user.id
    if replace:
        for key, row in existing.items():
            if key not in clean:
                await session.delete(row)
                changes[key] = {"before": row.value, "after": None}
    if changes:
        record_audit(
            session,
            event_type=CONFIG_EVENT,
            actor_user_id=user.id,
            metadata={
                "changes": {
                    key: {
                        "before": _mask(key, value["before"]),
                        "after": _mask(key, value["after"]),
                    }
                    for key, value in changes.items()
                }
            },
        )
    await session.flush()
    overrides = await load_overrides(session)
    apply_overrides(settings, overrides, base)
    return config_payload(settings, overrides)


def _mask(key: str, value: Any) -> Any:
    if key.endswith("password") or "secret" in key or "api_key" in key:
        return "***"
    return value


def export_payload(settings: Settings, overrides: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "exportedAt": datetime.now(UTC).isoformat(),
        "values": {
            spec.key: overrides.get(spec.key, getattr(settings, spec.key)) for spec in SPECS
        },
    }


__all__ = [
    "CONFIG_EVENT",
    "CONFIG_VERSION",
    "GROUPS",
    "SPECS",
    "apply_overrides",
    "capture_base",
    "config_payload",
    "export_payload",
    "load_overrides",
    "save_overrides",
    "validate_values",
]
