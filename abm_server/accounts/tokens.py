from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.security import digest_token
from ..errors import ApiError
from ..models import AccountToken, User, UserStatus, utcnow
from .service import as_utc

PURPOSE_EMAIL_VERIFY = "email_verify"
PURPOSE_PASSWORD_RESET = "password_reset"


async def issue_account_token(
    session: AsyncSession,
    *,
    user: User,
    purpose: str,
    ttl_seconds: int,
) -> str:
    now = utcnow()
    await session.execute(
        delete(AccountToken).where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == purpose,
            AccountToken.expires_at <= now,
        )
    )
    raw = secrets.token_urlsafe(32)
    session.add(
        AccountToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=digest_token(raw),
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    )
    await session.flush()
    return raw


async def consume_account_token(
    session: AsyncSession,
    *,
    raw_token: str,
    purpose: str,
) -> User:
    token = await session.scalar(
        select(AccountToken).where(
            AccountToken.token_hash == digest_token(raw_token),
            AccountToken.purpose == purpose,
        )
    )
    if (
        token is None
        or token.used_at is not None
        or (as_utc(token.expires_at) or datetime.now(UTC)) <= datetime.now(UTC)
    ):
        raise ApiError(
            400,
            "ABM_TOKEN_INVALID",
            "This link is invalid or has expired.",
        )
    user = await session.get(User, token.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise ApiError(
            403,
            "ABM_ACCOUNT_DISABLED",
            "Account is disabled or does not exist.",
            action="reauthenticate",
        )
    token.used_at = utcnow()
    return user
