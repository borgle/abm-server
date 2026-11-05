from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import Depends, Request
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounts import as_utc, find_session_by_token
from ..database import get_session
from ..errors import ApiError
from ..models import AccountSession, ApiKey, User, UserRole, UserStatus
from .security import digest_token

SESSION_COOKIE = "abm_session"
CSRF_COOKIE = "abm_csrf"


@dataclass(slots=True)
class AuthContext:
    user: User
    account_session: AccountSession


@dataclass(slots=True)
class RuntimeAuth:
    user: User
    api_key: ApiKey | None = None
    auth_kind: str = "api_key"
    scopes: tuple[str, ...] = ()
    access_token_id: str | None = None
    connection_mode: str = "auto"
    connection_ids: tuple[str, ...] = ()


def set_auth_cookies(
    response: Response,
    *,
    session_token: str,
    csrf_token: str,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _origin_key(value: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    return scheme, (parsed.hostname or "").lower(), parsed.port or default_port


async def get_current_auth(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> AuthContext:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError(401, "ABM_SESSION_EXPIRED", "Session is missing or expired.")
    account_session = await find_session_by_token(db, token)
    now = datetime.now(UTC)
    expires_at = as_utc(account_session.expires_at) if account_session else None
    if (
        account_session is None
        or account_session.revoked_at is not None
        or expires_at is None
        or expires_at <= now
    ):
        raise ApiError(401, "ABM_SESSION_EXPIRED", "Session is missing or expired.")
    user = account_session.user
    if user.status != UserStatus.ACTIVE:
        raise ApiError(
            403,
            "ABM_ACCOUNT_DISABLED",
            "Account is disabled.",
            action="reauthenticate",
        )
    last_seen = as_utc(account_session.last_seen_at)
    if last_seen is None or now - last_seen >= timedelta(minutes=5):
        account_session.last_seen_at = now
        # Commit immediately: an open UPDATE keeps SQLite's write lock for the
        # whole request, so other writers (research runner, publishing, session
        # bookkeeping) fail with "database is locked" after the busy timeout.
        # Losing this touch is harmless, so a failed commit must not fail auth.
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
    return AuthContext(user=user, account_session=account_session)


async def get_optional_auth(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> AuthContext | None:
    try:
        return await get_current_auth(request, db)
    except ApiError:
        return None


async def require_csrf(
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
) -> AuthContext:
    csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
    csrf_header = request.headers.get("x-csrf-token", "")
    if (
        not csrf_cookie
        or not csrf_header
        or csrf_cookie != csrf_header
        or digest_token(csrf_header) != auth.account_session.csrf_hash
    ):
        raise ApiError(403, "ABM_CSRF_INVALID", "CSRF validation failed.")

    origin = request.headers.get("origin")
    if origin:
        allowed_origins = {_origin_key(str(request.base_url))}
        public_base_url = request.app.state.settings.public_base_url
        if public_base_url:
            allowed_origins.add(_origin_key(public_base_url))
        if _origin_key(origin) not in allowed_origins:
            raise ApiError(403, "ABM_CSRF_INVALID", "Untrusted request origin.")
    return auth


async def require_admin(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
    if auth.user.role != UserRole.ADMIN:
        raise ApiError(403, "ABM_FORBIDDEN", "Administrator permission required.")
    return auth


async def require_admin_csrf(
    auth: AuthContext = Depends(require_csrf),
) -> AuthContext:
    if auth.user.role != UserRole.ADMIN:
        raise ApiError(403, "ABM_FORBIDDEN", "Administrator permission required.")
    return auth


async def get_runtime_auth(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> RuntimeAuth:
    from ..api_keys import resolve_api_key

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        plaintext = authorization[7:].strip()
    else:
        plaintext = request.headers.get("x-abm-api-key", "").strip()
    api_key, user = await resolve_api_key(db, plaintext)
    await db.commit()
    return RuntimeAuth(
        user=user,
        api_key=api_key,
        auth_kind="api_key",
        scopes=("browser", "account:read", "account:write"),
    )


async def get_video_auth(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> RuntimeAuth:
    """Accept a short-lived bridge token or a normal API Key for video routes."""
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        plaintext = authorization[7:].strip()
    else:
        plaintext = request.headers.get("x-abm-api-key", "").strip()

    if not plaintext.startswith("abm_bridge_"):
        return await get_runtime_auth(request, db)

    service = getattr(request.app.state, "video_service", None)
    api_key_id = service.resolve_bridge_token(plaintext) if service else None
    if api_key_id is None:
        raise ApiError(
            401,
            "ABM_INVALID_TOKEN",
            "Invalid or expired bridge token.",
        )
    api_key = await db.get(ApiKey, api_key_id)
    if api_key is None or api_key.revoked_at is not None:
        raise ApiError(401, "ABM_INVALID_API_KEY", "API Key revoked.")
    user = await db.get(User, api_key.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise ApiError(
            403,
            "ABM_ACCOUNT_DISABLED",
            "Account is disabled.",
            action="reauthenticate",
        )
    return RuntimeAuth(
        user=user,
        api_key=api_key,
        auth_kind="bridge_token",
        scopes=("browser",),
    )
