"""Account tier lookup.

The open-source edition has a single local tier. Hosted deployments resolve
free/pro from plan code and expiry via the private cloud package.
"""

from __future__ import annotations

from datetime import datetime

from .config import Settings
from .models import User

LOCAL_TIER = "local"


def tier_for(user: User, settings: Settings, now: datetime | None = None) -> str:
    if (settings.edition or "hosted").strip().lower() == "single":
        return LOCAL_TIER
    from abm_cloud.tiers import tier_for as cloud_tier

    return cloud_tier(user, now)


def is_pro_tier(tier: str) -> bool:
    return tier == "pro"
