from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AccountAuditEvent


def record_audit(
    session: AsyncSession,
    *,
    event_type: str,
    actor_user_id: str | None = None,
    subject_user_id: str | None = None,
    api_key_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        AccountAuditEvent(
            actor_user_id=actor_user_id,
            subject_user_id=subject_user_id,
            api_key_id=api_key_id,
            event_type=event_type,
            event_metadata=metadata or {},
        )
    )
