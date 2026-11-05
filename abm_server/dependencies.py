"""Backward-compatible re-export for auth dependencies."""

from .auth.dependencies import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    AuthContext,
    RuntimeAuth,
    clear_auth_cookies,
    get_current_auth,
    get_runtime_auth,
    require_admin,
    require_admin_csrf,
    require_csrf,
    set_auth_cookies,
)

__all__ = [
    "CSRF_COOKIE",
    "SESSION_COOKIE",
    "AuthContext",
    "RuntimeAuth",
    "clear_auth_cookies",
    "get_current_auth",
    "get_runtime_auth",
    "require_admin",
    "require_admin_csrf",
    "require_csrf",
    "set_auth_cookies",
]
