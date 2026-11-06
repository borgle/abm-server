"""Quota policies for the single-user edition.

Content quotas used to be read from a plan JSON. The open-source edition has no
plans: limits come from environment settings and default to unlimited. The
hosted edition supplies ``abm_cloud.plans.PlanQuotaPolicy`` privately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import User


@dataclass(frozen=True, slots=True)
class Limits:
    generations_per_day: int = 0
    tokens_per_month: int = 0
    images_per_day: int = 0
    image_max_n: int = 4
    storage_bytes: int = 0
    research_pages_per_month: int = 0
    browser_connections: int = 5
    browser_sessions: int = 3
    reserved_priority_slots: int = 1


class QuotaPolicy(Protocol):
    async def limits(
        self,
        session: AsyncSession,
        user: User,
        config: dict[str, Any] | None = None,
    ) -> Limits: ...

    async def browser_limits(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> tuple[int, int, int]: ...


class LocalQuotaPolicy:
    """Single-user edition: quotas come from the environment, not plans."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def limits(
        self,
        session: AsyncSession,
        user: User,
        config: dict[str, Any] | None = None,
    ) -> Limits:
        return Limits(
            generations_per_day=self.settings.local_generations_per_day,
            tokens_per_month=self.settings.local_tokens_per_month,
            images_per_day=self.settings.local_images_per_day,
            image_max_n=self.settings.local_image_max_n,
            storage_bytes=self.settings.local_storage_bytes,
            research_pages_per_month=self.settings.local_research_pages_per_month,
            browser_connections=self.settings.local_browser_connections,
            browser_sessions=self.settings.local_browser_sessions,
            reserved_priority_slots=self.settings.local_reserved_priority_slots,
        )

    async def browser_limits(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> tuple[int, int, int]:
        return (
            self.settings.local_browser_connections,
            self.settings.local_browser_sessions,
            self.settings.local_reserved_priority_slots,
        )


def quota_policy(settings: Settings) -> QuotaPolicy:
    if (settings.edition or "hosted").strip().lower() == "single":
        return LocalQuotaPolicy(settings)
    from abm_cloud.plans import PlanQuotaPolicy

    return PlanQuotaPolicy(settings)
