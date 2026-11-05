"""Social login state and account-linking rules."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..accounts import (
    REGISTRATION_APPROVAL_SETTING,
    as_utc,
    ensure_user_can_login,
    get_setting,
    get_user_by_email,
    normalize_email,
    register_social_user,
)
from ..audit import record_audit
from ..auth.security import digest_token
from ..config import Settings
from ..errors import ApiError
from ..models import (
    ExternalIdentity,
    SocialLoginState,
    SocialPendingRegistration,
    User,
    utcnow,
)
from .providers import SocialProfile, SocialProvider

PROVIDER_NAMES = {
    "wechat": "WeChat",
    "qq": "QQ",
    "google": "Google",
    "github": "GitHub",
    "microsoft": "Microsoft",
}
EMAIL_LESS_PROVIDERS = {"wechat", "qq"}


class SocialEmailConflict(ApiError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            409,
            "ABM_SOCIAL_EMAIL_CONFLICT",
            message
            or (
                "An account with this email already exists. Sign in with your "
                "password and link this provider from the account page."
            ),
            action="sign_in_with_password",
        )


class SocialPendingInvalid(ApiError):
    def __init__(self) -> None:
        super().__init__(
            400,
            "ABM_SOCIAL_PENDING_INVALID",
            "Social registration link is invalid or expired. Start again.",
            action="retry",
        )


class SocialEmailRequired(ApiError):
    def __init__(self) -> None:
        super().__init__(
            400,
            "ABM_SOCIAL_EMAIL_REQUIRED",
            "This provider does not return an email address.",
            action="complete_registration",
        )


@dataclass(slots=True)
class SocialLoginOutcome:
    user: User
    identity: ExternalIdentity
    created: bool


def provider_name(provider_id: str) -> str:
    return PROVIDER_NAMES.get(provider_id, provider_id)


def provider_requires_email(provider_id: str) -> bool:
    return provider_id in EMAIL_LESS_PROVIDERS


def _avatar(value: str | None) -> str | None:
    return value[:500] if value else None


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def create_login_state(
    session: AsyncSession,
    *,
    settings: Settings,
    provider: SocialProvider,
    next_path: str,
    link_user_id: str | None,
) -> tuple[str, str, str]:
    raw_state = secrets.token_urlsafe(32)
    browser_token = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    await session.execute(delete(SocialLoginState).where(SocialLoginState.expires_at < utcnow()))
    session.add(
        SocialLoginState(
            state_hash=digest_token(raw_state),
            browser_hash=digest_token(browser_token),
            provider=provider.id,
            code_verifier=code_verifier,
            next_path=next_path[:500],
            link_user_id=link_user_id,
            expires_at=utcnow() + timedelta(seconds=settings.social_login_state_ttl_seconds),
        )
    )
    await session.flush()
    return raw_state, browser_token, _code_challenge(code_verifier)


async def consume_login_state(
    session: AsyncSession,
    *,
    provider_id: str,
    raw_state: str,
    browser_token: str,
) -> SocialLoginState:
    state = await session.scalar(
        select(SocialLoginState).where(
            SocialLoginState.state_hash == digest_token(raw_state),
            SocialLoginState.provider == provider_id,
        )
    )
    if (
        state is None
        or state.used_at is not None
        or as_utc(state.expires_at) <= utcnow()
        or not browser_token
        or not secrets.compare_digest(state.browser_hash, digest_token(browser_token))
    ):
        raise ApiError(
            400,
            "ABM_SOCIAL_STATE_INVALID",
            "Social login request is invalid or expired. Start again.",
            action="retry",
        )
    state.used_at = utcnow()
    await session.flush()
    return state


async def _find_identity(
    session: AsyncSession,
    *,
    provider: str,
    subject: str,
) -> ExternalIdentity | None:
    return await session.scalar(
        select(ExternalIdentity)
        .options(selectinload(ExternalIdentity.user))
        .where(
            ExternalIdentity.provider == provider,
            ExternalIdentity.subject == subject,
        )
    )


async def create_pending_registration(
    session: AsyncSession,
    *,
    settings: Settings,
    provider: SocialProvider,
    profile: SocialProfile,
    next_path: str,
) -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(32)
    browser_token = secrets.token_urlsafe(32)
    await session.execute(
        delete(SocialPendingRegistration).where(SocialPendingRegistration.expires_at < utcnow())
    )
    session.add(
        SocialPendingRegistration(
            token_hash=digest_token(raw_token),
            browser_hash=digest_token(browser_token),
            provider=provider.id,
            subject=profile.subject,
            display_name=profile.display_name,
            avatar_url=_avatar(profile.avatar_url),
            next_path=next_path[:500],
            expires_at=utcnow() + timedelta(seconds=settings.social_login_state_ttl_seconds),
        )
    )
    await session.flush()
    return raw_token, browser_token


async def get_pending_registration(
    session: AsyncSession,
    *,
    raw_token: str,
    browser_token: str,
) -> SocialPendingRegistration:
    pending = await session.scalar(
        select(SocialPendingRegistration).where(
            SocialPendingRegistration.token_hash == digest_token(raw_token)
        )
    )
    if (
        pending is None
        or pending.used_at is not None
        or as_utc(pending.expires_at) <= utcnow()
        or not browser_token
        or not secrets.compare_digest(pending.browser_hash, digest_token(browser_token))
    ):
        raise SocialPendingInvalid()
    return pending


async def complete_pending_registration(
    session: AsyncSession,
    *,
    pending: SocialPendingRegistration,
    email: str,
    display_name: str,
    settings: Settings,
) -> User:
    now = utcnow()
    identity = await _find_identity(
        session,
        provider=pending.provider,
        subject=pending.subject,
    )
    if identity is not None:
        pending.used_at = now
        await session.flush()
        ensure_user_can_login(identity.user)
        return identity.user

    normalized_email = normalize_email(email)
    existing_user = await get_user_by_email(session, normalized_email)
    if existing_user is not None:
        raise SocialEmailConflict(
            "This email already has an account. Sign in with your password, "
            "then link this provider from Account → Sign-in methods."
        )

    require_approval = bool(
        await get_setting(
            session,
            REGISTRATION_APPROVAL_SETTING,
            settings.registration_require_approval,
        )
    )
    provider_label = provider_name(pending.provider)
    user = await register_social_user(
        session,
        email=normalized_email,
        display_name=display_name.strip()[:120] or pending.display_name,
        provider=provider_label,
        registration_require_approval=require_approval,
        email_verified=False,
    )
    identity = ExternalIdentity(
        user_id=user.id,
        provider=pending.provider,
        subject=pending.subject,
        email=normalized_email,
        email_verified=False,
        display_name=display_name.strip()[:120] or pending.display_name,
        avatar_url=pending.avatar_url,
        last_login_at=now,
    )
    session.add(identity)
    pending.used_at = now
    await session.flush()
    return user


async def complete_login(
    session: AsyncSession,
    *,
    provider: SocialProvider,
    profile: SocialProfile,
    settings: Settings,
) -> SocialLoginOutcome:
    now = utcnow()
    identity = await _find_identity(
        session,
        provider=provider.id,
        subject=profile.subject,
    )
    if identity is not None:
        user = identity.user
        ensure_user_can_login(user)
        identity.last_login_at = now
        if profile.display_name:
            identity.display_name = profile.display_name
        if profile.avatar_url:
            identity.avatar_url = _avatar(profile.avatar_url)
        if profile.email and profile.email_verified:
            identity.email = normalize_email(profile.email)
            identity.email_verified = True
            if user.email_verified_at is None:
                user.email_verified_at = now
        await session.flush()
        return SocialLoginOutcome(user=user, identity=identity, created=False)

    if profile.email is None:
        raise SocialEmailRequired()

    if not profile.email_verified:
        raise ApiError(
            403,
            "ABM_SOCIAL_EMAIL_UNVERIFIED",
            "The provider did not confirm a verified email address.",
            action="use_password",
        )

    existing_user = await get_user_by_email(session, profile.email)
    if existing_user is not None:
        if existing_user.email_verified_at is None:
            raise SocialEmailConflict()
        ensure_user_can_login(existing_user)
        identity = ExternalIdentity(
            user_id=existing_user.id,
            provider=provider.id,
            subject=profile.subject,
            email=normalize_email(profile.email),
            email_verified=True,
            display_name=profile.display_name,
            avatar_url=_avatar(profile.avatar_url),
            last_login_at=now,
        )
        session.add(identity)
        await session.flush()
        record_audit(
            session,
            event_type="ABM_ACCOUNT_SOCIAL_LINKED",
            actor_user_id=existing_user.id,
            subject_user_id=existing_user.id,
            metadata={"provider": provider.id},
        )
        return SocialLoginOutcome(user=existing_user, identity=identity, created=False)

    require_approval = bool(
        await get_setting(
            session,
            REGISTRATION_APPROVAL_SETTING,
            settings.registration_require_approval,
        )
    )
    user = await register_social_user(
        session,
        email=profile.email,
        display_name=profile.display_name,
        provider=provider_name(provider.id),
        registration_require_approval=require_approval,
    )
    identity = ExternalIdentity(
        user_id=user.id,
        provider=provider.id,
        subject=profile.subject,
        email=normalize_email(profile.email),
        email_verified=True,
        display_name=profile.display_name,
        avatar_url=_avatar(profile.avatar_url),
        last_login_at=now,
    )
    session.add(identity)
    await session.flush()
    return SocialLoginOutcome(user=user, identity=identity, created=True)


async def finish_link(
    session: AsyncSession,
    *,
    user: User,
    provider: SocialProvider,
    profile: SocialProfile,
) -> ExternalIdentity:
    now = utcnow()
    if profile.email is None:
        identity_email = normalize_email(user.email)
        provider_email_verified = False
    else:
        if not profile.email_verified:
            raise ApiError(
                403,
                "ABM_SOCIAL_EMAIL_UNVERIFIED",
                "The provider did not confirm a verified email address.",
                action="use_password",
            )
        if normalize_email(profile.email) != normalize_email(user.email):
            raise ApiError(
                409,
                "ABM_SOCIAL_LINK_MISMATCH",
                "The provider email does not match this account email.",
                action="use_matching_account",
            )
        identity_email = normalize_email(profile.email)
        provider_email_verified = True

    identity = await _find_identity(
        session,
        provider=provider.id,
        subject=profile.subject,
    )
    if identity is not None:
        if identity.user_id != user.id:
            raise ApiError(
                409,
                "ABM_SOCIAL_LINK_TAKEN",
                "This provider account is already linked to another ABM account.",
                action="use_another_provider",
            )
        if provider_email_verified:
            identity.email = identity_email
            identity.email_verified = True
        identity.display_name = profile.display_name
        identity.avatar_url = _avatar(profile.avatar_url)
        identity.last_login_at = now
        await session.flush()
        return identity

    identity = ExternalIdentity(
        user_id=user.id,
        provider=provider.id,
        subject=profile.subject,
        email=identity_email,
        email_verified=provider_email_verified,
        display_name=profile.display_name,
        avatar_url=_avatar(profile.avatar_url),
        last_login_at=now,
    )
    session.add(identity)
    if provider_email_verified and user.email_verified_at is None:
        user.email_verified_at = now
    await session.flush()
    record_audit(
        session,
        event_type="ABM_ACCOUNT_SOCIAL_LINKED",
        actor_user_id=user.id,
        subject_user_id=user.id,
        metadata={"provider": provider.id},
    )
    return identity


async def list_identities(
    session: AsyncSession,
    *,
    user_id: str,
) -> list[ExternalIdentity]:
    rows = await session.scalars(
        select(ExternalIdentity)
        .where(ExternalIdentity.user_id == user_id)
        .order_by(ExternalIdentity.linked_at.desc())
    )
    return list(rows)


async def unlink_identity(
    session: AsyncSession,
    *,
    user_id: str,
    identity_id: str,
) -> ExternalIdentity:
    identity = await session.get(ExternalIdentity, identity_id)
    if identity is None or identity.user_id != user_id:
        raise ApiError(404, "ABM_NOT_FOUND", "Linked account not found.")
    await session.delete(identity)
    record_audit(
        session,
        event_type="ABM_ACCOUNT_SOCIAL_UNLINKED",
        actor_user_id=user_id,
        subject_user_id=user_id,
        metadata={"provider": identity.provider},
    )
    await session.flush()
    return identity
