"""Persistent account notifications shown in the web console."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from ..database import Database
from ..models import AccountNotice, utcnow


class NotificationService:
    def __init__(self, database: Database):
        self.database = database

    async def create(
        self,
        *,
        user_id: str,
        kind: str,
        title: str,
        body: str | None = None,
        action_url: str | None = None,
        dedupe_minutes: int = 0,
    ) -> AccountNotice | None:
        async with self.database.sessions() as db:
            if dedupe_minutes > 0:
                cutoff = utcnow() - timedelta(minutes=dedupe_minutes)
                recent = await db.scalar(
                    select(AccountNotice)
                    .where(
                        AccountNotice.user_id == user_id,
                        AccountNotice.kind == kind,
                        AccountNotice.created_at >= cutoff,
                    )
                    .order_by(AccountNotice.created_at.desc())
                )
                if recent is not None:
                    return None
            notice = AccountNotice(
                user_id=user_id,
                kind=kind,
                title=title[:200],
                body=body,
                action_url=action_url,
            )
            db.add(notice)
            await db.commit()
            await db.refresh(notice)
            return notice

    async def list(self, user_id: str, *, limit: int = 20) -> list[AccountNotice]:
        async with self.database.sessions() as db:
            rows = await db.scalars(
                select(AccountNotice)
                .where(AccountNotice.user_id == user_id)
                .order_by(AccountNotice.created_at.desc())
                .limit(max(1, min(limit, 100)))
            )
            return list(rows)

    async def mark_read(self, user_id: str, notice_id: str) -> bool:
        async with self.database.sessions() as db:
            notice = await db.get(AccountNotice, notice_id)
            if notice is None or notice.user_id != user_id:
                return False
            if notice.read_at is None:
                notice.read_at = utcnow()
                await db.commit()
            return True

    async def mark_all_read(self, user_id: str) -> None:
        async with self.database.sessions() as db:
            rows = await db.scalars(
                select(AccountNotice).where(
                    AccountNotice.user_id == user_id,
                    AccountNotice.read_at.is_(None),
                )
            )
            for notice in rows:
                notice.read_at = utcnow()
            await db.commit()
