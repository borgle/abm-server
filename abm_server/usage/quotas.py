from __future__ import annotations

from typing import Any

from ..config import Settings


def quota_for_plan(plan: str, settings: Settings) -> dict[str, int]:
    pro = plan == "pro"
    return {
        "toolCalls": settings.quota_tool_calls_pro if pro else settings.quota_tool_calls_free,
        "videoBytes": settings.quota_video_bytes_pro if pro else settings.quota_video_bytes_free,
        "videoJobs": settings.quota_video_jobs_pro if pro else settings.quota_video_jobs_free,
    }


def quota_status(totals: dict[str, int], quota: dict[str, int]) -> dict[str, Any]:
    def item(used: int, limit: int) -> dict[str, Any]:
        if limit <= 0:
            return {
                "used": used,
                "limit": limit,
                "percent": 100.0 if used > 0 else 0.0,
                "over": used > 0,
            }
        return {
            "used": used,
            "limit": limit,
            "percent": round(min(used / limit * 100, 999.9), 1),
            "over": used > limit,
        }

    return {
        "toolCalls": item(totals.get("toolCalls", 0), quota["toolCalls"]),
        "videoBytes": item(totals.get("videoBytes", 0), quota["videoBytes"]),
        "videoJobs": item(totals.get("videoJobs", 0), quota["videoJobs"]),
    }
