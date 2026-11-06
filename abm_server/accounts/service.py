from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..audit import record_audit
from ..auth.security import (
    digest_token,
    hash_password,
    new_csrf_token,
    new_session_token,
    verify_password,
)
from ..config import Settings
from ..errors import ApiError
from ..models import (
    AccountSession,
    Setting,
    User,
    UserRole,
    UserStatus,
    utcnow,
)

REGISTRATION_APPROVAL_SETTING = "registration_require_approval"


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def get_setting(
    session: AsyncSession,
    key: str,
    default: object = None,
) -> object:
    row = await session.get(Setting, key)
    return default if row is None else row.value


async def set_setting(
    session: AsyncSession,
    key: str,
    value: object,
    *,
    updated_by: str | None,
) -> Setting:
    row = await session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value, updated_by=updated_by)
        session.add(row)
    else:
        row.value = value
        row.updated_by = updated_by
        row.updated_at = utcnow()
    return row


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == normalize_email(email)))


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    application_note: str | None,
    registration_require_approval: bool,
) -> User | None:
    try:
        from abm_cloud.accounts import register_user as provision
    except ImportError as exc:
        raise ApiError(
            403,
            "ABM_REGISTRATION_DISABLED",
            "Registration is disabled on this server.",
        ) from exc
    return await provision(
        session,
        email=email,
        password=password,
        display_name=display_name,
        application_note=application_note,
        registration_require_approval=registration_require_approval,
    )


async def authenticate_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
) -> User:
    user = await get_user_by_email(session, email)
    if user is None or not verify_password(password, user.password_hash):
        raise ApiError(401, "ABM_INVALID_CREDENTIALS", "Incorrect email or password.")
    ensure_user_can_login(user)
    return user


def ensure_user_can_login(user: User) -> None:
    status_errors = {
        UserStatus.PENDING: (
            "ABM_ACCOUNT_PENDING",
            "Account is awaiting administrator approval.",
            "none",
        ),
        UserStatus.REJECTED: (
            "ABM_ACCOUNT_REJECTED",
            "Account request was rejected.",
            "none",
        ),
        UserStatus.DISABLED: (
            "ABM_ACCOUNT_DISABLED",
            "Account is disabled. Contact an administrator.",
            "reauthenticate",
        ),
    }
    if user.status in status_errors:
        code, message, action = status_errors[UserStatus(user.status)]
        raise ApiError(403, code, message, action=action)


async def register_social_user(
    session: AsyncSession,
    *,
    email: str,
    display_name: str,
    provider: str,
    registration_require_approval: bool,
    email_verified: bool = True,
) -> User:
    """Create a user from a social profile through the hosted provisioner."""

    try:
        from abm_cloud.accounts import register_social_user as provision
    except ImportError as exc:
        raise ApiError(
            403,
            "ABM_REGISTRATION_DISABLED",
            "Social registration is disabled on this server.",
        ) from exc
    return await provision(
        session,
        email=email,
        display_name=display_name,
        provider=provider,
        registration_require_approval=registration_require_approval,
        email_verified=email_verified,
    )


async def create_account_session(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    user_agent: str | None,
    ip_address: str | None,
    auth_method: str = "password",
    provider: str | None = None,
) -> tuple[AccountSession, str, str]:
    token = new_session_token()
    csrf_token = new_csrf_token()
    now = utcnow()
    account_session = AccountSession(
        user_id=user.id,
        token_hash=digest_token(token),
        csrf_hash=digest_token(csrf_token),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        last_seen_at=now,
        user_agent=(user_agent or "")[:512] or None,
        ip_address=(ip_address or "")[:64] or None,
    )
    session.add(account_session)
    await session.flush()
    record_audit(
        session,
        event_type="ABM_ACCOUNT_LOGIN",
        actor_user_id=user.id,
        subject_user_id=user.id,
        metadata={
            "sessionId": account_session.id,
            "method": auth_method,
            "ipAddress": account_session.ip_address,
            "userAgent": account_session.user_agent,
            **({"provider": provider} if provider else {}),
        },
    )
    return account_session, token, csrf_token


async def find_session_by_token(
    session: AsyncSession,
    token: str,
) -> AccountSession | None:
    return await session.scalar(
        select(AccountSession)
        .options(selectinload(AccountSession.user))
        .where(AccountSession.token_hash == digest_token(token))
    )


async def revoke_session(session: AsyncSession, account_session: AccountSession) -> None:
    if account_session.revoked_at is None:
        account_session.revoked_at = utcnow()


async def list_user_sessions(
    session: AsyncSession,
    user_id: str,
) -> list[AccountSession]:
    now = utcnow()
    rows = await session.scalars(
        select(AccountSession)
        .where(
            AccountSession.user_id == user_id,
            AccountSession.revoked_at.is_(None),
            AccountSession.expires_at > now,
        )
        .order_by(AccountSession.last_seen_at.desc())
    )
    return list(rows)


async def revoke_session_by_id(
    session: AsyncSession,
    *,
    user_id: str,
    session_id: str,
) -> bool:
    account_session = await session.get(AccountSession, session_id)
    if account_session is None or account_session.user_id != user_id:
        return False
    if account_session.revoked_at is None:
        account_session.revoked_at = utcnow()
        record_audit(
            session,
            event_type="ABM_ACCOUNT_SESSION_REVOKED",
            actor_user_id=user_id,
            subject_user_id=user_id,
            metadata={"sessionId": session_id},
        )
    return True


async def revoke_user_sessions(
    session: AsyncSession,
    *,
    user_id: str,
    except_session_id: str | None = None,
) -> None:
    query = select(AccountSession).where(
        AccountSession.user_id == user_id,
        AccountSession.revoked_at.is_(None),
    )
    if except_session_id is not None:
        query = query.where(AccountSession.id != except_session_id)
    for row in (await session.scalars(query)).all():
        row.revoked_at = utcnow()


async def initialize_identity_state(session: AsyncSession, settings: Settings) -> None:
    approval = await session.get(Setting, REGISTRATION_APPROVAL_SETTING)
    if approval is None:
        session.add(
            Setting(
                key=REGISTRATION_APPROVAL_SETTING,
                value=settings.registration_require_approval,
            )
        )

    admin_count = await session.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
    )
    if not admin_count and settings.bootstrap_admin_email and settings.bootstrap_admin_password:
        email = normalize_email(settings.bootstrap_admin_email)
        password = settings.bootstrap_admin_password
        if len(password) < settings.password_min_length:
            raise RuntimeError(
                f"ABM_BOOTSTRAP_ADMIN_PASSWORD must be at least "
                f"{settings.password_min_length} characters"
            )
        user = await get_user_by_email(session, email)
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(password),
                display_name="Administrator",
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
                plan_code="pro",
                approved_at=utcnow(),
            )
            session.add(user)
            await session.flush()
            record_audit(
                session,
                event_type="ABM_ADMIN_BOOTSTRAPPED",
                subject_user_id=user.id,
                metadata={},
            )
        else:
            user.role = UserRole.ADMIN
            user.status = UserStatus.ACTIVE
            user.approved_at = user.approved_at or utcnow()
    await session.commit()
