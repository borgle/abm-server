from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ...auth.dependencies import AuthContext, get_current_auth
from ...tiers import tier_for
from ...usage.quotas import quota_for_plan, quota_status

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


@router.get("/summary")
async def usage_summary(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    auth: AuthContext = Depends(get_current_auth),
) -> dict:
    settings = request.app.state.settings
    summary = await request.app.state.usage_service.summary(
        auth.user.id,
        days=days,
    )
    plan = tier_for(auth.user, settings)
    summary["plan"] = plan
    summary["quotas"] = quota_status(
        summary["totals"],
        quota_for_plan(plan, settings),
    )
    return summary
