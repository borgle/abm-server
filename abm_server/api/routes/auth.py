from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...accounts import (
    REGISTRATION_APPROVAL_SETTING,
    authenticate_user,
    create_account_session,
    get_setting,
    get_user_by_email,
    list_user_sessions,
    normalize_email,
    register_user,
    revoke_session,
    revoke_session_by_id,
    revoke_user_sessions,
)
from ...accounts.tokens import (
    PURPOSE_EMAIL_VERIFY,
    PURPOSE_PASSWORD_RESET,
    consume_account_token,
    issue_account_token,
)
from ...api_keys import list_user_api_keys
from ...audit import record_audit
from ...auth.dependencies import (
    CSRF_COOKIE,
    AuthContext,
    clear_auth_cookies,
    get_current_auth,
    require_csrf,
    set_auth_cookies,
)
from ...auth.security import hash_password, verify_password
from ...database import get_session
from ...errors import ApiError
from ...extension_gateway import SessionError
from ...models import AccountAuditEvent, ExternalIdentity, User, UserRole, UserStatus, utcnow
from ...schemas import (
    AcceptedResponse,
    AccountDeleteRequest,
    AuthResponse,
    EmailRequest,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    RegisterRequest,
    TokenConfirmRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_PROVIDER_NAMES = {
    "wechat": "WeChat",
    "qq": "QQ",
    "google": "Google",
    "github": "GitHub",
    "microsoft": "Microsoft",
}
_EMAIL_LESS_PROVIDERS = {"wechat", "qq"}


def _provider_name(provider_id: str) -> str:
    return _PROVIDER_NAMES.get(provider_id, provider_id)


def _social_providers(settings) -> list[dict[str, object]]:
    if not settings.social_login_enabled:
        return []
    try:
        from abm_cloud.social import public_provider_descriptors
    except ImportError:
        return []
    return public_provider_descriptors(settings)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _enforce_rate_limit(request: Request, bucket: str) -> None:
    settings = request.app.state.settings
    retry_after = await request.app.state.registration_limiter.hit(
        bucket,
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    if retry_after:
        raise ApiError(
            429,
            "ABM_RATE_LIMITED",
            "Rate limit exceeded. Try again later.",
            retryable=True,
            action="wait",
        )


@router.post("/register", response_model=AcceptedResponse, status_code=202)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> AcceptedResponse:
    settings = request.app.state.settings
    if not request.app.state.edition.self_registration:
        raise ApiError(
            403,
            "ABM_REGISTRATION_DISABLED",
            "Registration is disabled on this server.",
        )
    await _enforce_rate_limit(request, f"register:{_client_ip(request)}")
    if len(payload.password) < settings.password_min_length:
        raise ApiError(
            400,
            "ABM_VALIDATION_ERROR",
            f"Password must be at least {settings.password_min_length} characters.",
        )
    require_approval = bool(
        await get_setting(
            db,
            REGISTRATION_APPROVAL_SETTING,
            settings.registration_require_approval,
        )
    )
    await register_user(
        db,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        application_note=payload.application_note,
        registration_require_approval=require_approval,
    )
    await db.commit()
    return AcceptedResponse()


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    settings = request.app.state.settings
    email = normalize_email(payload.email)
    await _enforce_rate_limit(request, f"login:{_client_ip(request)}:{email}")
    user = await authenticate_user(db, email=email, password=payload.password)
    account_session, session_token, csrf_token = await create_account_session(
        db,
        user=user,
        settings=settings,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    await db.commit()
    response = JSONResponse(
        AuthResponse(user=UserResponse.model_validate(user), csrf_token=csrf_token).model_dump(
            by_alias=True,
            mode="json",
        )
    )
    set_auth_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        max_age=settings.session_ttl_seconds,
        secure=settings.session_cookie_secure,
    )
    return response


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Response:
    await revoke_session(db, auth.account_session)
    record_audit(
        db,
        event_type="ABM_ACCOUNT_LOGOUT",
        actor_user_id=auth.user.id,
        subject_user_id=auth.user.id,
        metadata={"sessionId": auth.account_session.id},
    )
    await db.commit()
    response = Response(status_code=204)
    clear_auth_cookies(response)
    return response


def _public_base_url(request: Request) -> str:
    settings = request.app.state.settings
    return settings.public_base_url.strip().rstrip("/") or str(request.base_url).rstrip("/")


@router.post("/password-reset/request", response_model=AcceptedResponse, status_code=202)
async def request_password_reset(
    payload: EmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> AcceptedResponse:
    await _enforce_rate_limit(request, f"password-reset:{_client_ip(request)}")
    settings = request.app.state.settings
    email = normalize_email(str(payload.email))
    user = await get_user_by_email(db, email)
    if user is not None and user.status == UserStatus.ACTIVE:
        raw = await issue_account_token(
            db,
            user=user,
            purpose=PURPOSE_PASSWORD_RESET,
            ttl_seconds=settings.password_reset_ttl_seconds,
        )
        link = f"{_public_base_url(request)}/reset-password?token={quote(raw)}"
        try:
            await request.app.state.email_service.send_password_reset(
                to=user.email,
                link=link,
            )
        except Exception:
            logger.exception("Failed to send password reset email")
        await db.commit()
    return AcceptedResponse(status="accepted")


@router.post(
    "/password-reset/confirm",
    response_model=AcceptedResponse,
    status_code=202,
)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> AcceptedResponse:
    settings = request.app.state.settings
    if len(payload.new_password) < settings.password_min_length:
        raise ApiError(
            400,
            "ABM_VALIDATION_ERROR",
            f"Password must be at least {settings.password_min_length} characters.",
        )
    user = await consume_account_token(
        db,
        raw_token=payload.token,
        purpose=PURPOSE_PASSWORD_RESET,
    )
    user.password_hash = hash_password(payload.new_password)
    user.updated_at = utcnow()
    await revoke_user_sessions(db, user_id=user.id)
    await request.app.state.oauth_service.revoke_user_tokens(db, user_id=user.id)
    record_audit(
        db,
        event_type="ABM_ACCOUNT_PASSWORD_RESET",
        actor_user_id=user.id,
        subject_user_id=user.id,
    )
    await db.commit()
    return AcceptedResponse(status="accepted")


@router.post(
    "/email-verification/request",
    response_model=AcceptedResponse,
    status_code=202,
)
async def request_email_verification(
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> AcceptedResponse:
    settings = request.app.state.settings
    if auth.user.email_verified_at is not None:
        return AcceptedResponse(status="already_verified")
    raw = await issue_account_token(
        db,
        user=auth.user,
        purpose=PURPOSE_EMAIL_VERIFY,
        ttl_seconds=settings.email_verification_ttl_seconds,
    )
    link = f"{_public_base_url(request)}/verify-email?token={quote(raw)}"
    try:
        await request.app.state.email_service.send_verification(
            to=auth.user.email,
            link=link,
        )
    except Exception:
        logger.exception("Failed to send verification email")
    await db.commit()
    return AcceptedResponse(status="accepted")


@router.post("/email-verification/confirm", response_model=AcceptedResponse, status_code=202)
async def confirm_email_verification(
    payload: TokenConfirmRequest,
    db: AsyncSession = Depends(get_session),
) -> AcceptedResponse:
    user = await consume_account_token(
        db,
        raw_token=payload.token,
        purpose=PURPOSE_EMAIL_VERIFY,
    )
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
        user.updated_at = utcnow()
    await db.commit()
    return AcceptedResponse(status="verified")


@router.get("/me", response_model=UserResponse)
async def me(auth: AuthContext = Depends(get_current_auth)) -> UserResponse:
    return UserResponse.model_validate(auth.user)


@router.get("/sessions")
async def list_sessions(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await list_user_sessions(db, auth.user.id)
    return {
        "items": [
            {
                "id": row.id,
                "current": row.id == auth.account_session.id,
                "createdAt": row.created_at.isoformat(),
                "lastSeenAt": row.last_seen_at.isoformat(),
                "expiresAt": row.expires_at.isoformat(),
                "userAgent": row.user_agent,
                "ipAddress": row.ip_address,
            }
            for row in rows
        ]
    }


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_account_session(
    session_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Response:
    if session_id == auth.account_session.id:
        raise ApiError(
            400,
            "ABM_VALIDATION_ERROR",
            "Use sign out to end the current session.",
        )
    if not await revoke_session_by_id(
        db,
        user_id=auth.user.id,
        session_id=session_id,
    ):
        raise ApiError(404, "ABM_NOT_FOUND", "Session not found.")
    await db.commit()
    return Response(status_code=204)


@router.post("/sessions/revoke-others", status_code=204)
async def revoke_other_account_sessions(
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Response:
    await revoke_user_sessions(
        db,
        user_id=auth.user.id,
        except_session_id=auth.account_session.id,
    )
    await db.commit()
    return Response(status_code=204)


@router.get("/account/export")
async def export_account(
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    keys = await list_user_api_keys(db, auth.user.id)
    sessions = await list_user_sessions(db, auth.user.id)
    audits = list(
        await db.scalars(
            select(AccountAuditEvent)
            .where(
                (AccountAuditEvent.actor_user_id == auth.user.id)
                | (AccountAuditEvent.subject_user_id == auth.user.id)
            )
            .order_by(AccountAuditEvent.created_at.desc())
            .limit(200)
        )
    )
    usage = await request.app.state.usage_service.summary(auth.user.id, days=365)
    identities = list(
        await db.scalars(
            select(ExternalIdentity)
            .where(ExternalIdentity.user_id == auth.user.id)
            .order_by(ExternalIdentity.linked_at.desc())
        )
    )
    payload = {
        "exportedAt": utcnow().isoformat(),
        "user": UserResponse.model_validate(auth.user).model_dump(
            by_alias=True,
            mode="json",
        ),
        "socialIdentities": [
            {
                "provider": identity.provider,
                "providerName": _provider_name(identity.provider),
                "email": identity.email,
                "emailVerified": identity.email_verified,
                "linkedAt": identity.linked_at.isoformat(),
                "lastLoginAt": (
                    identity.last_login_at.isoformat() if identity.last_login_at else None
                ),
            }
            for identity in identities
        ],
        "apiKeys": [
            {
                "id": key.id,
                "name": key.name,
                "prefix": key.public_prefix,
                "status": "revoked" if key.revoked_at else "active",
                "createdAt": key.created_at.isoformat(),
                "lastUsedAt": key.last_used_at.isoformat() if key.last_used_at else None,
                "revokedAt": key.revoked_at.isoformat() if key.revoked_at else None,
            }
            for key in keys
        ],
        "sessions": [
            {
                "id": row.id,
                "createdAt": row.created_at.isoformat(),
                "lastSeenAt": row.last_seen_at.isoformat(),
                "expiresAt": row.expires_at.isoformat(),
                "userAgent": row.user_agent,
                "ipAddress": row.ip_address,
            }
            for row in sessions
        ],
        "usage": usage,
        "audit": [
            {
                "eventType": row.event_type,
                "createdAt": row.created_at.isoformat(),
                "metadata": row.event_metadata,
            }
            for row in audits
        ],
    }
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": (f'attachment; filename="abm-export-{auth.user.id[:8]}.json"'),
        },
    )


@router.delete("/account", status_code=204)
async def delete_account(
    payload: AccountDeleteRequest,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Response:
    if not verify_password(payload.password, auth.user.password_hash):
        raise ApiError(401, "ABM_INVALID_CREDENTIALS", "Current password is incorrect.")
    if auth.user.role == UserRole.ADMIN:
        admin_count = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.role == UserRole.ADMIN,
                User.status == UserStatus.ACTIVE,
            )
        )
        if (admin_count or 0) <= 1:
            raise ApiError(
                400,
                "ABM_VALIDATION_ERROR",
                "The last administrator account cannot be deleted.",
            )

    await request.app.state.oauth_service.revoke_user_tokens(
        db,
        user_id=auth.user.id,
    )
    await request.app.state.extension_gateway.close_for_user(
        auth.user.id,
        SessionError(
            "ABM_ACCOUNT_DELETED",
            "Account deleted.",
            1008,
            action="reauthenticate",
        ),
    )
    await db.delete(auth.user)
    await db.commit()
    response = Response(status_code=204)
    clear_auth_cookies(response)
    return response


@router.patch("/password", status_code=204)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Response:
    settings = request.app.state.settings
    if not verify_password(payload.current_password, auth.user.password_hash):
        raise ApiError(401, "ABM_INVALID_CREDENTIALS", "Current password is incorrect.")
    if len(payload.new_password) < settings.password_min_length:
        raise ApiError(
            400,
            "ABM_VALIDATION_ERROR",
            f"New password must be at least {settings.password_min_length} characters.",
        )
    auth.user.password_hash = hash_password(payload.new_password)
    auth.user.updated_at = utcnow()
    await revoke_user_sessions(
        db,
        user_id=auth.user.id,
        except_session_id=auth.account_session.id,
    )
    record_audit(
        db,
        event_type="ABM_PASSWORD_CHANGED",
        actor_user_id=auth.user.id,
        subject_user_id=auth.user.id,
        metadata={},
    )
    await db.commit()
    return Response(status_code=204)


@router.get("/identities")
async def account_identities(
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    identities = list(
        await db.scalars(
            select(ExternalIdentity)
            .where(ExternalIdentity.user_id == auth.user.id)
            .order_by(ExternalIdentity.linked_at.desc())
        )
    )
    providers = _social_providers(request.app.state.settings)
    return {
        "items": [
            {
                "id": identity.id,
                "provider": identity.provider,
                "providerName": _provider_name(identity.provider),
                "email": identity.email,
                "emailVerified": identity.email_verified,
                "requiresEmail": identity.provider in _EMAIL_LESS_PROVIDERS,
                "displayName": identity.display_name,
                "linkedAt": identity.linked_at.isoformat(),
                "lastLoginAt": (
                    identity.last_login_at.isoformat() if identity.last_login_at else None
                ),
            }
            for identity in identities
        ],
        "providers": providers,
        "email": auth.user.email,
        "emailNormalized": normalize_email(auth.user.email),
        "account": UserResponse.model_validate(auth.user).model_dump(
            by_alias=True,
            mode="json",
        ),
    }


@router.delete("/identities/{identity_id}", status_code=204)
async def remove_account_identity(
    identity_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Response:
    identity = await db.get(ExternalIdentity, identity_id)
    if identity is None or identity.user_id != auth.user.id:
        raise ApiError(404, "ABM_NOT_FOUND", "Linked account not found.")
    await db.delete(identity)
    record_audit(
        db,
        event_type="ABM_ACCOUNT_SOCIAL_UNLINKED",
        actor_user_id=auth.user.id,
        subject_user_id=auth.user.id,
        metadata={"provider": identity.provider},
    )
    await db.commit()
    return Response(status_code=204)


def auth_response_for_user(user: User, csrf_token: str) -> AuthResponse:
    return AuthResponse(user=UserResponse.model_validate(user), csrf_token=csrf_token)


def session_metadata(request: Request) -> dict[str, str | None]:
    return {
        "csrfCookie": request.cookies.get(CSRF_COOKIE),
        "loginAt": datetime.now(UTC).isoformat(),
    }
