from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounts import as_utc
from ..audit import record_audit
from ..auth.security import api_key_prefix, digest_token, generate_api_key
from ..config import Settings
from ..errors import ApiError
from ..models import ApiKey, User, UserStatus, utcnow
from ..tiers import is_pro_tier, tier_for


def key_limit_for_user(user: User, settings: Settings) -> int:
    return (
        settings.max_active_keys_pro
        if is_pro_tier(tier_for(user, settings))
        else settings.max_active_keys_free
    )


async def active_key_count(session: AsyncSession, user_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(ApiKey)
            .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        )
        or 0
    )


async def create_api_key(
    session: AsyncSession,
    *,
    user: User,
    name: str,
    settings: Settings,
) -> tuple[ApiKey, str]:
    count = await active_key_count(session, user.id)
    limit = key_limit_for_user(user, settings)
    if count >= limit:
        raise ApiError(
            409,
            "ABM_KEY_LIMIT_REACHED",
            f"Current plan allows at most {limit} active API keys.",
        )
    prefix, plaintext, key_hash = generate_api_key()
    api_key = ApiKey(
        user_id=user.id,
        name=name,
        public_prefix=prefix,
        key_hash=key_hash,
    )
    session.add(api_key)
    await session.flush()
    record_audit(
        session,
        event_type="ABM_API_KEY_CREATED",
        actor_user_id=user.id,
        subject_user_id=user.id,
        api_key_id=api_key.id,
        metadata={"prefix": prefix, "name": name},
    )
    return api_key, plaintext


async def list_user_api_keys(session: AsyncSession, user_id: str) -> list[ApiKey]:
    rows = await session.scalars(
        select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
    )
    return list(rows)


async def revoke_api_key(
    session: AsyncSession,
    *,
    user: User,
    key_id: str,
) -> ApiKey:
    api_key = await session.get(ApiKey, key_id)
    if api_key is None or api_key.user_id != user.id:
        raise ApiError(404, "ABM_KEY_NOT_FOUND", "API Key not found.")
    if api_key.revoked_at is not None:
        raise ApiError(409, "ABM_KEY_ALREADY_REVOKED", "API Key already revoked.")
    api_key.revoked_at = utcnow()
    api_key.revoked_by = user.id
    record_audit(
        session,
        event_type="ABM_API_KEY_REVOKED",
        actor_user_id=user.id,
        subject_user_id=user.id,
        api_key_id=api_key.id,
        metadata={"prefix": api_key.public_prefix},
    )
    return api_key


async def resolve_api_key(
    session: AsyncSession,
    plaintext: str,
    *,
    touch: bool = True,
) -> tuple[ApiKey, User]:
    if not plaintext or not plaintext.startswith("abm_"):
        raise ApiError(401, "ABM_INVALID_API_KEY", "Invalid API Key.")
    prefix = api_key_prefix(plaintext)
    if prefix is None:
        raise ApiError(401, "ABM_INVALID_API_KEY", "Invalid API Key.")
    api_key = await session.scalar(
        select(ApiKey).where(
            ApiKey.public_prefix == prefix,
            ApiKey.key_hash == digest_token(plaintext),
        )
    )
    if api_key is None:
        raise ApiError(401, "ABM_INVALID_API_KEY", "Invalid API Key.")
    if api_key.revoked_at is not None:
        raise ApiError(
            401,
            "ABM_API_KEY_REVOKED",
            "API Key revoked.",
            action="open_account_portal",
        )
    user = await session.get(User, api_key.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise ApiError(
            403,
            "ABM_ACCOUNT_DISABLED",
            "Account is disabled.",
            action="reauthenticate",
        )
    if touch:
        now = datetime.now(UTC)
        last_used = as_utc(api_key.last_used_at)
        if last_used is None or (now - last_used).total_seconds() >= 60:
            api_key.last_used_at = now
    return api_key, user
