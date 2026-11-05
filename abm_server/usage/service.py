"""Daily usage counters for hosted billing and quotas."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from ..config import Settings
from ..database import Database
from ..models import UsageAlert, UsageDaily, utcnow
from .quotas import quota_for_plan


class UsageService:
    def __init__(self, database: Database):
        self.database = database
        self._lock = asyncio.Lock()

    @staticmethod
    def _day() -> str:
        return datetime.now(UTC).date().isoformat()

    async def _add(
        self,
        *,
        user_id: str,
        api_key_id: str,
        tool_calls: int = 0,
        video_jobs: int = 0,
        video_bytes: int = 0,
    ) -> None:
        if not (tool_calls or video_jobs or video_bytes):
            return
        day = self._day()
        async with self._lock, self.database.sessions() as db:
            row = await db.scalar(
                select(UsageDaily).where(
                    UsageDaily.api_key_id == api_key_id,
                    UsageDaily.day == day,
                )
            )
            if row is None:
                row = UsageDaily(
                    user_id=user_id,
                    api_key_id=api_key_id,
                    day=day,
                    tool_calls=0,
                    video_jobs=0,
                    video_bytes=0,
                )
                db.add(row)
            row.tool_calls += tool_calls
            row.video_jobs += video_jobs
            row.video_bytes += video_bytes
            row.updated_at = utcnow()
            await db.commit()

    async def record_tool_call(self, *, user_id: str, api_key_id: str) -> None:
        await self._add(user_id=user_id, api_key_id=api_key_id, tool_calls=1)

    async def record_video(
        self,
        *,
        user_id: str,
        api_key_id: str,
        relayed_bytes: int,
    ) -> None:
        await self._add(
            user_id=user_id,
            api_key_id=api_key_id,
            video_jobs=1,
            video_bytes=max(0, relayed_bytes),
        )

    async def month_totals_for_users(
        self,
        user_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        if not user_ids:
            return {}
        month_start = datetime.now(UTC).date().replace(day=1).isoformat()
        async with self.database.sessions() as db:
            rows = await db.execute(
                select(
                    UsageDaily.user_id,
                    func.sum(UsageDaily.tool_calls),
                    func.sum(UsageDaily.video_jobs),
                    func.sum(UsageDaily.video_bytes),
                )
                .where(
                    UsageDaily.user_id.in_(user_ids),
                    UsageDaily.day >= month_start,
                )
                .group_by(UsageDaily.user_id)
            )
        return {
            str(row[0]): {
                "toolCalls": int(row[1] or 0),
                "videoJobs": int(row[2] or 0),
                "videoBytes": int(row[3] or 0),
            }
            for row in rows
        }

    async def current_month_totals(
        self,
        *,
        user_id: str,
        api_key_id: str,
    ) -> dict[str, int]:
        month_start = datetime.now(UTC).date().replace(day=1).isoformat()
        async with self.database.sessions() as db:
            rows = list(
                await db.scalars(
                    select(UsageDaily).where(
                        UsageDaily.user_id == user_id,
                        UsageDaily.api_key_id == api_key_id,
                        UsageDaily.day >= month_start,
                    )
                )
            )
        return {
            "toolCalls": sum(row.tool_calls for row in rows),
            "videoJobs": sum(row.video_jobs for row in rows),
            "videoBytes": sum(row.video_bytes for row in rows),
        }

    async def exceeded_metrics(
        self,
        *,
        user_id: str,
        api_key_id: str,
        plan: str,
        settings: Settings,
    ) -> list[str]:
        if settings.quota_enforcement != "hard":
            return []
        quota = quota_for_plan(plan, settings)
        totals = await self.current_month_totals(
            user_id=user_id,
            api_key_id=api_key_id,
        )
        exceeded = []
        if quota["toolCalls"] > 0 and totals["toolCalls"] >= quota["toolCalls"]:
            exceeded.append("tool_calls")
        if quota["videoBytes"] > 0 and totals["videoBytes"] >= quota["videoBytes"]:
            exceeded.append("video_bytes")
        if quota["videoJobs"] > 0 and totals["videoJobs"] >= quota["videoJobs"]:
            exceeded.append("video_jobs")
        return exceeded

    async def crossed_thresholds(
        self,
        *,
        user_id: str,
        api_key_id: str,
        plan: str,
        settings: Settings,
    ) -> int | None:
        quotas = quota_for_plan(plan, settings)
        totals = await self.current_month_totals(
            user_id=user_id,
            api_key_id=api_key_id,
        )
        ratios = []
        if quotas["toolCalls"] > 0:
            ratios.append(totals["toolCalls"] / quotas["toolCalls"])
        if quotas["videoBytes"] > 0:
            ratios.append(totals["videoBytes"] / quotas["videoBytes"])
        if quotas["videoJobs"] > 0:
            ratios.append(totals["videoJobs"] / quotas["videoJobs"])
        reached = {
            threshold for ratio in ratios for threshold in (80, 100) if ratio * 100 >= threshold
        }
        if not reached:
            return None

        month = datetime.now(UTC).strftime("%Y-%m")
        async with self._lock, self.database.sessions() as db:
            existing = set(
                await db.scalars(
                    select(UsageAlert.threshold).where(
                        UsageAlert.api_key_id == api_key_id,
                        UsageAlert.month == month,
                    )
                )
            )
            new = sorted(reached - existing)
            for threshold in new:
                db.add(
                    UsageAlert(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        month=month,
                        threshold=threshold,
                    )
                )
            await db.commit()
        return max(new) if new else None

    async def summary(self, user_id: str, *, days: int = 30) -> dict[str, Any]:
        window = max(1, min(days, 365))
        since = (datetime.now(UTC).date() - timedelta(days=window - 1)).isoformat()
        async with self.database.sessions() as db:
            rows = list(
                await db.scalars(
                    select(UsageDaily)
                    .where(
                        UsageDaily.user_id == user_id,
                        UsageDaily.day >= since,
                    )
                    .order_by(UsageDaily.day.desc())
                )
            )
        totals = {
            "toolCalls": sum(row.tool_calls for row in rows),
            "videoJobs": sum(row.video_jobs for row in rows),
            "videoBytes": sum(row.video_bytes for row in rows),
        }
        by_key: dict[str, dict[str, int]] = {}
        for row in rows:
            item = by_key.setdefault(
                row.api_key_id,
                {"toolCalls": 0, "videoJobs": 0, "videoBytes": 0},
            )
            item["toolCalls"] += row.tool_calls
            item["videoJobs"] += row.video_jobs
            item["videoBytes"] += row.video_bytes
        return {
            "days": window,
            "totals": totals,
            "byKey": [{"apiKeyId": key, **values} for key, values in by_key.items()],
            "daily": [
                {
                    "day": row.day,
                    "toolCalls": row.tool_calls,
                    "videoJobs": row.video_jobs,
                    "videoBytes": row.video_bytes,
                }
                for row in rows
            ],
        }
