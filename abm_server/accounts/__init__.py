"""Account lifecycle, settings, sessions, and identity bootstrap."""

from .maintenance import cleanup_account_sessions
from .service import (
    REGISTRATION_APPROVAL_SETTING,
    as_utc,
    authenticate_user,
    create_account_session,
    ensure_user_can_login,
    find_session_by_token,
    get_setting,
    get_user_by_email,
    initialize_identity_state,
    list_user_sessions,
    normalize_email,
    register_social_user,
    register_user,
    revoke_session,
    revoke_session_by_id,
    revoke_user_sessions,
    set_setting,
)

__all__ = [
    "REGISTRATION_APPROVAL_SETTING",
    "as_utc",
    "authenticate_user",
    "cleanup_account_sessions",
    "create_account_session",
    "ensure_user_can_login",
    "find_session_by_token",
    "get_setting",
    "get_user_by_email",
    "initialize_identity_state",
    "list_user_sessions",
    "normalize_email",
    "register_social_user",
    "register_user",
    "revoke_session",
    "revoke_session_by_id",
    "revoke_user_sessions",
    "set_setting",
]
