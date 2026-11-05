from __future__ import annotations

import logging
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...accounts import (
    create_account_session,
    normalize_email,
)
from ...accounts.tokens import PURPOSE_EMAIL_VERIFY, issue_account_token
from ...auth.dependencies import (
    AuthContext,
    get_current_auth,
    get_optional_auth,
    require_csrf,
    set_auth_cookies,
)
from ...config import Settings
from ...database import get_session
from ...errors import ApiError
from ...models import User, UserStatus
from ...schemas import SocialCompleteRequest, UserResponse
from ...social import (
    SocialEmailRequired,
    SocialProviderError,
    build_authorize_url,
    complete_login,
    complete_pending_registration,
    consume_login_state,
    create_login_state,
    create_pending_registration,
    exchange_code_for_profile,
    finish_link,
    get_pending_registration,
    get_social_provider,
    list_identities,
    provider_name,
    provider_requires_email,
    public_provider_descriptors,
    unlink_identity,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


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


PENDING_COOKIE = "abm_social_pending"


def _public_base_url(request: Request) -> str:
    settings = request.app.state.settings
    return settings.public_base_url.strip().rstrip("/") or str(request.base_url).rstrip("/")


def _safe_next(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return fallback
    return value


def _with_query(path: str, **params: str) -> str:
    base, _, fragment = path.partition("#")
    separator = "&" if "?" in base else "?"
    result = f"{base}{separator}{urlencode(params)}"
    if fragment:
        result = f"{result}#{fragment}"
    return result


def _redirect_error(next_path: str, code: str, provider: str | None = None) -> RedirectResponse:
    params = {"social_error": code}
    if provider:
        params["provider"] = provider
    target = _with_query("/login", **params)
    if next_path and next_path != "/login":
        target = _with_query(target, next=next_path)
    return RedirectResponse(target, status_code=303)


def _callback_uri(request: Request, provider_id: str) -> str:
    return f"{_public_base_url(request)}/api/v1/auth/social/{provider_id}/callback"


def _state_cookie(provider_id: str) -> str:
    return f"abm_social_state_{provider_id}"


def _set_state_cookie(
    response: RedirectResponse,
    *,
    provider_id: str,
    token: str,
    settings: Settings,
) -> None:
    response.set_cookie(
        _state_cookie(provider_id),
        token,
        max_age=settings.social_login_state_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/api/v1/auth/social",
    )


def _clear_state_cookie(response: RedirectResponse, provider_id: str) -> RedirectResponse:
    response.delete_cookie(
        _state_cookie(provider_id),
        path="/api/v1/auth/social",
    )
    return response


def _set_pending_cookie(response: Response, *, token: str, settings: Settings) -> None:
    response.set_cookie(
        PENDING_COOKIE,
        token,
        max_age=settings.social_login_state_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_pending_cookie(response: Response) -> Response:
    response.delete_cookie(PENDING_COOKIE, path="/")
    return response


@router.get("/social/providers")
async def social_providers(request: Request) -> dict:
    return {"items": public_provider_descriptors(request.app.state.settings)}


@router.get("/social/{provider_id}/start")
async def social_start(
    provider_id: str,
    request: Request,
    next: str | None = Query(default=None),
    link: bool = Query(default=False),
    auth: AuthContext | None = Depends(get_optional_auth),
    db: AsyncSession = Depends(get_session),
):
    settings = request.app.state.settings
    provider = get_social_provider(settings, provider_id)
    if provider is None:
        raise ApiError(
            404,
            "ABM_SOCIAL_DISABLED",
            "This social login provider is not configured.",
        )

    link_user: User | None = None
    if link:
        if auth is None:
            start_path = _with_query(
                f"/api/v1/auth/social/{provider_id}/start",
                **{"next": next or "/console#account", "link": "1"},
            )
            return RedirectResponse(
                f"/login?next={quote(start_path, safe='')}",
                status_code=303,
            )
        link_user = auth.user

    fallback = "/console#account" if link else "/console"
    next_path = _safe_next(next, fallback)
    await _enforce_rate_limit(request, f"social-start:{_client_ip(request)}")

    raw_state, browser_token, code_challenge = await create_login_state(
        db,
        settings=settings,
        provider=provider,
        next_path=next_path,
        link_user_id=link_user.id if link_user else None,
    )
    await db.commit()
    url = build_authorize_url(
        provider,
        redirect_uri=_callback_uri(request, provider.id),
        state=raw_state,
        code_challenge=code_challenge,
    )
    response = RedirectResponse(url, status_code=303)
    _set_state_cookie(
        response,
        provider_id=provider.id,
        token=browser_token,
        settings=settings,
    )
    return response


@router.get("/social/{provider_id}/callback")
async def social_callback(
    provider_id: str,
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    db: AsyncSession = Depends(get_session),
):
    settings = request.app.state.settings
    provider = get_social_provider(settings, provider_id)
    if provider is None:
        return _redirect_error("/login", "social_disabled", provider_id)
    if not state:
        return _clear_state_cookie(
            _redirect_error("/login", "state_invalid", provider_id),
            provider_id,
        )

    browser_token = request.cookies.get(_state_cookie(provider_id), "")
    try:
        saved_state = await consume_login_state(
            db,
            provider_id=provider_id,
            raw_state=state,
            browser_token=browser_token,
        )
        await db.commit()
    except ApiError:
        await db.rollback()
        return _clear_state_cookie(
            _redirect_error("/login", "state_invalid", provider_id),
            provider_id,
        )

    def error_response(target: str, code: str) -> RedirectResponse:
        return _clear_state_cookie(
            _redirect_error(target, code, provider_id),
            provider_id,
        )

    next_path = _safe_next(saved_state.next_path, "/console")
    if error:
        return error_response(next_path, "cancelled")
    if not code:
        return error_response(next_path, "provider_error")

    try:
        profile = await exchange_code_for_profile(
            provider,
            code=code,
            redirect_uri=_callback_uri(request, provider.id),
            code_verifier=saved_state.code_verifier,
        )
    except SocialProviderError:
        logger.warning("Social provider exchange failed for %s", provider_id)
        return error_response(next_path, "provider_error")
    except Exception:
        logger.exception("Unexpected social provider failure for %s", provider_id)
        return error_response(next_path, "provider_error")

    if saved_state.link_user_id:
        user = await db.get(User, saved_state.link_user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            return error_response("/login", "account_disabled")
        try:
            await finish_link(db, user=user, provider=provider, profile=profile)
            await db.commit()
        except ApiError as exc:
            await db.rollback()
            return error_response(next_path, _error_code(exc))
        return _clear_state_cookie(
            RedirectResponse(
                _with_query(next_path, social="linked", provider=provider.id),
                status_code=303,
            ),
            provider_id,
        )

    try:
        outcome = await complete_login(
            db,
            provider=provider,
            profile=profile,
            settings=settings,
        )
        await db.commit()
    except SocialEmailRequired:
        await db.rollback()
        raw_pending, pending_browser_token = await create_pending_registration(
            db,
            settings=settings,
            provider=provider,
            profile=profile,
            next_path=next_path,
        )
        await db.commit()
        response = RedirectResponse(
            f"/social/complete?token={quote(raw_pending)}",
            status_code=303,
        )
        _set_pending_cookie(
            response,
            token=pending_browser_token,
            settings=settings,
        )
        return _clear_state_cookie(response, provider_id)
    except ApiError as exc:
        await db.rollback()
        return error_response(next_path, _error_code(exc))

    if outcome.user.status != UserStatus.ACTIVE:
        return error_response(next_path, _error_code_for_status(outcome.user.status))

    account_session, session_token, csrf_token = await create_account_session(
        db,
        user=outcome.user,
        settings=settings,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
        auth_method="social",
        provider=provider.id,
    )
    await db.commit()
    response = RedirectResponse(
        _with_query(next_path, social="login", provider=provider.id),
        status_code=303,
    )
    set_auth_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        max_age=settings.session_ttl_seconds,
        secure=settings.session_cookie_secure,
    )
    return _clear_state_cookie(response, provider_id)


def _error_code(exc: ApiError) -> str:
    mapping = {
        "ABM_SOCIAL_STATE_INVALID": "state_invalid",
        "ABM_SOCIAL_EMAIL_UNVERIFIED": "email_unverified",
        "ABM_SOCIAL_EMAIL_CONFLICT": "email_conflict",
        "ABM_ACCOUNT_PENDING": "account_pending",
        "ABM_ACCOUNT_REJECTED": "account_rejected",
        "ABM_ACCOUNT_DISABLED": "account_disabled",
        "ABM_SOCIAL_LINK_MISMATCH": "link_mismatch",
        "ABM_SOCIAL_LINK_TAKEN": "link_taken",
        "ABM_RATE_LIMITED": "rate_limited",
    }
    return mapping.get(exc.code, "unknown")


def _error_code_for_status(status: str) -> str:
    if status == UserStatus.PENDING:
        return "account_pending"
    if status == UserStatus.REJECTED:
        return "account_rejected"
    return "account_disabled"


@router.get("/social/pending/{token}")
async def social_pending_info(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> dict:
    pending = await get_pending_registration(
        db,
        raw_token=token,
        browser_token=request.cookies.get(PENDING_COOKIE, ""),
    )
    return {
        "provider": pending.provider,
        "providerName": provider_name(pending.provider),
        "displayName": pending.display_name,
        "nextPath": pending.next_path,
        "expiresAt": pending.expires_at.isoformat(),
    }


async def _send_verification_email(
    request: Request,
    user: User,
    raw_token: str | None,
) -> None:
    if raw_token is None:
        return
    link = f"{_public_base_url(request)}/verify-email?token={quote(raw_token)}"
    try:
        await request.app.state.email_service.send_verification(to=user.email, link=link)
    except Exception:
        logger.exception("Failed to send social registration verification email")


@router.post("/social/complete")
async def social_complete(
    payload: SocialCompleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    settings = request.app.state.settings
    await _enforce_rate_limit(request, f"social-complete:{_client_ip(request)}")
    pending = await get_pending_registration(
        db,
        raw_token=payload.token,
        browser_token=request.cookies.get(PENDING_COOKIE, ""),
    )
    try:
        user = await complete_pending_registration(
            db,
            pending=pending,
            email=str(payload.email),
            display_name=payload.display_name,
            settings=settings,
        )
    except ApiError:
        await db.rollback()
        raise

    verification_token = None
    if user.email_verified_at is None:
        verification_token = await issue_account_token(
            db,
            user=user,
            purpose=PURPOSE_EMAIL_VERIFY,
            ttl_seconds=settings.email_verification_ttl_seconds,
        )

    if user.status != UserStatus.ACTIVE:
        await db.commit()
        await _send_verification_email(request, user, verification_token)
        response = JSONResponse({"status": "pending"}, status_code=202)
        return _clear_pending_cookie(response)

    _account_session, session_token, csrf_token = await create_account_session(
        db,
        user=user,
        settings=settings,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
        auth_method="social",
        provider=pending.provider,
    )
    await db.commit()
    await _send_verification_email(request, user, verification_token)
    response = JSONResponse(
        {
            "status": "active",
            "user": UserResponse.model_validate(user).model_dump(
                by_alias=True,
                mode="json",
            ),
            "csrfToken": csrf_token,
            "next": pending.next_path,
        }
    )
    set_auth_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        max_age=settings.session_ttl_seconds,
        secure=settings.session_cookie_secure,
    )
    return _clear_pending_cookie(response)


@router.get("/identities")
async def account_identities(
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    identities = await list_identities(db, user_id=auth.user.id)
    providers = public_provider_descriptors(request.app.state.settings)
    return {
        "items": [
            {
                "id": identity.id,
                "provider": identity.provider,
                "providerName": provider_name(identity.provider),
                "email": identity.email,
                "emailVerified": identity.email_verified,
                "requiresEmail": provider_requires_email(identity.provider),
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
    await unlink_identity(
        db,
        user_id=auth.user.id,
        identity_id=identity_id,
    )
    await db.commit()
    return Response(status_code=204)
