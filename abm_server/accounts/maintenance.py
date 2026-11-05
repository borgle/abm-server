"""Retention maintenance for account sessions.

Sessions keep their sign-in IP and user agent, so they are pruned once they are
both past the retention window and no longer usable. The cleanup is idempotent
and safe to run at any time.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, or_

from ..database import Database
from ..models import AccountSession, utcnow


async def cleanup_account_sessions(
    database: Database,
    *,
    retention_days: int = 90,
    now: datetime | None = None,
) -> int:
    """Delete sessions whose sign-in metadata is older than the retention window."""
    moment = now or utcnow()
    cutoff = moment - timedelta(days=max(1, retention_days))
    async with database.sessions() as session:
        result = await session.execute(
            delete(AccountSession).where(
                or_(
                    AccountSession.expires_at <= cutoff,
                    AccountSession.revoked_at.is_not(None) & (AccountSession.revoked_at <= cutoff),
                )
            )
        )
        await session.commit()
        return int(result.rowcount or 0)


__all__ = ["cleanup_account_sessions"]
