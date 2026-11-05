"""Research job and source services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...errors import ApiError
from ...models import (
    CreationAsset,
    CreationAssetVersion,
    CreationJobEvent,
    CreationResearchJob,
    CreationSource,
    User,
    utcnow,
)
from ..service import get_project
from .planner import (
    DEPTH_PAGE_BUDGET,
    ENGINE_IDS,
    build_plan,
    pages_for_depth,
    plan_summary,
)

JOB_STATUSES = {
    "queued",
    "running",
    "paused",
    "needs_attention",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "interrupted",
}
ACTIVE_STATUSES = {"queued", "running", "paused", "needs_attention"}


def job_dict(job: CreationResearchJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "projectId": job.project_id,
        "status": job.status,
        "keywords": job.keywords or [],
        "exclusions": job.exclusions or [],
        "engines": job.engines or [],
        "depth": job.depth,
        "language": job.language,
        "plan": job.plan or [],
        "progress": job.progress or {},
        "totalQueries": job.total_queries,
        "completedQueries": job.completed_queries,
        "pagesCollected": job.pages_collected,
        "pagesFailed": job.pages_failed,
        "errorCode": job.error_code,
        "errorMessage": job.error_message,
        "attention": job.attention,
        "createdAt": job.created_at.isoformat(),
        "updatedAt": job.updated_at.isoformat(),
        "startedAt": job.started_at.isoformat() if job.started_at else None,
        "finishedAt": job.finished_at.isoformat() if job.finished_at else None,
    }


def event_dict(event: CreationJobEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "seq": event.seq,
        "level": event.level,
        "message": event.message,
        "data": event.data or {},
        "createdAt": event.created_at.isoformat(),
    }


def source_dict(source: CreationSource, *, include_content: bool = False) -> dict[str, Any]:
    payload = {
        "id": source.id,
        "jobId": source.job_id,
        "projectId": source.project_id,
        "url": source.url,
        "canonicalUrl": source.canonical_url,
        "domain": source.domain,
        "title": source.title,
        "author": source.author,
        "publishedAt": source.published_at,
        "language": source.language,
        "kind": source.kind,
        "engine": source.engine,
        "excerpt": source.excerpt,
        "contentLength": source.content_length,
        "credibility": source.credibility,
        "factors": source.factors or {},
        "metrics": source.metrics or {},
        "tags": source.tags or [],
        "fetchedAt": source.fetched_at.isoformat(),
        "trashedAt": source.trashed_at.isoformat() if source.trashed_at else None,
        "purgeAfter": source.purge_after.isoformat() if source.purge_after else None,
        "trashReason": source.trash_reason,
    }
    if include_content:
        payload["contentText"] = source.content_text
    return payload


async def monthly_pages_used(session: AsyncSession, user_id: str) -> int:
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    return int(
        await session.scalar(
            select(func.count(CreationSource.id)).where(
                CreationSource.user_id == user_id,
                CreationSource.created_at >= month_start,
            )
        )
        or 0
    )


async def create_job(
    session: AsyncSession,
    user: User,
    *,
    keywords: list[str],
    exclusions: list[str] | None = None,
    engines: list[str] | None = None,
    depth: str = "standard",
    language: str = "zh",
    project_id: str | None = None,
    config: dict[str, Any],
    limits: Any | None = None,
) -> CreationResearchJob:
    if config.get("enabled") is False:
        raise ApiError(
            403,
            "ABM_CREATION_DISABLED",
            "The creation workspace is disabled by an administrator.",
        )
    if depth not in DEPTH_PAGE_BUDGET:
        raise ApiError(422, "ABM_VALIDATION_ERROR", "Unknown research depth.")
    if engines is not None:
        invalid = [engine for engine in engines if engine not in ENGINE_IDS]
        if invalid:
            raise ApiError(422, "ABM_VALIDATION_ERROR", "Unknown search engine.")
    if not keywords:
        raise ApiError(422, "ABM_VALIDATION_ERROR", "At least one keyword is required.")

    plan = build_plan(keywords, exclusions, engines, depth)
    if not plan:
        raise ApiError(422, "ABM_VALIDATION_ERROR", "Could not build a query plan.")

    if project_id:
        await get_project(session, user.id, project_id)

    if limits is None:
        monthly_limit = 0
    else:
        monthly_limit = int(getattr(limits, "research_pages_per_month", 0) or 0)
    budget = pages_for_depth(depth)
    if monthly_limit:
        used = await monthly_pages_used(session, user.id)
        if used + budget > monthly_limit:
            raise ApiError(
                409,
                "ABM_CREATION_QUOTA_EXCEEDED",
                "The monthly research page quota is exhausted.",
                retryable=False,
                action="upgrade",
            )

    plan_engines = sorted({engine for item in plan for engine in item["engines"]})
    summary = plan_summary(plan, depth)
    job = CreationResearchJob(
        user_id=user.id,
        project_id=project_id,
        status="queued",
        keywords=list(keywords[:5]),
        exclusions=list(exclusions or []),
        engines=plan_engines,
        depth=depth,
        language=language if language in {"zh", "en"} else "zh",
        plan=plan,
        progress={
            "queryIndex": 0,
            "engineIndex": 0,
            "visited": [],
            "collected": 0,
            "summary": summary,
        },
        total_queries=len(plan),
        completed_queries=0,
        pages_collected=0,
        pages_failed=0,
    )
    session.add(job)
    await session.flush()
    return job


async def list_jobs(
    session: AsyncSession,
    user_id: str,
    *,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[CreationResearchJob]:
    query = select(CreationResearchJob).where(CreationResearchJob.user_id == user_id)
    if status:
        query = query.where(CreationResearchJob.status == status)
    query = query.order_by(CreationResearchJob.created_at.desc()).limit(limit).offset(offset)
    return list((await session.scalars(query)).all())


async def count_jobs(
    session: AsyncSession,
    user_id: str,
    *,
    status: str | None = None,
) -> int:
    query = select(func.count(CreationResearchJob.id)).where(CreationResearchJob.user_id == user_id)
    if status:
        query = query.where(CreationResearchJob.status == status)
    return int(await session.scalar(query) or 0)


async def get_job(session: AsyncSession, user_id: str, job_id: str) -> CreationResearchJob:
    job = await session.get(CreationResearchJob, job_id)
    if job is None or job.user_id != user_id:
        raise ApiError(404, "ABM_NOT_FOUND", "Research job not found.")
    return job


async def count_active_jobs(session: AsyncSession, user_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count(CreationResearchJob.id)).where(
                CreationResearchJob.user_id == user_id,
                CreationResearchJob.status.in_(["queued", "running", "paused", "needs_attention"]),
            )
        )
        or 0
    )


async def list_events(
    session: AsyncSession,
    user_id: str,
    job_id: str,
    *,
    after_seq: int = 0,
    limit: int = 200,
    newest_first: bool = False,
) -> list[CreationJobEvent]:
    await get_job(session, user_id, job_id)
    order = CreationJobEvent.seq.desc() if newest_first else CreationJobEvent.seq
    query = (
        select(CreationJobEvent)
        .where(
            CreationJobEvent.job_id == job_id,
            CreationJobEvent.user_id == user_id,
            CreationJobEvent.seq > after_seq,
        )
        .order_by(order)
        .limit(limit)
    )
    rows = list((await session.scalars(query)).all())
    if newest_first:
        rows.reverse()
    return rows


async def list_sources(
    session: AsyncSession,
    user_id: str,
    *,
    query_text: str | None = None,
    domain: str | None = None,
    job_id: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CreationSource]:
    query = select(CreationSource).where(
        CreationSource.user_id == user_id,
        CreationSource.trashed_at.is_(None),
    )
    if job_id:
        query = query.where(CreationSource.job_id == job_id)
    if domain:
        query = query.where(CreationSource.domain == domain)
    if kind:
        query = query.where(CreationSource.kind == kind)
    if query_text:
        needle = f"%{query_text.strip()}%"
        query = query.where(
            or_(
                CreationSource.title.ilike(needle),
                CreationSource.excerpt.ilike(needle),
                CreationSource.content_text.ilike(needle),
            )
        )
    query = query.order_by(CreationSource.fetched_at.desc()).limit(limit).offset(offset)
    return list((await session.scalars(query)).all())


async def count_sources(
    session: AsyncSession,
    user_id: str,
    *,
    query_text: str | None = None,
    domain: str | None = None,
    job_id: str | None = None,
) -> int:
    query = select(func.count(CreationSource.id)).where(
        CreationSource.user_id == user_id,
        CreationSource.trashed_at.is_(None),
    )
    if job_id:
        query = query.where(CreationSource.job_id == job_id)
    if domain:
        query = query.where(CreationSource.domain == domain)
    if query_text:
        needle = f"%{query_text.strip()}%"
        query = query.where(
            or_(
                CreationSource.title.ilike(needle),
                CreationSource.excerpt.ilike(needle),
                CreationSource.content_text.ilike(needle),
            )
        )
    return int(await session.scalar(query) or 0)


async def get_source(session: AsyncSession, user_id: str, source_id: str) -> CreationSource:
    source = await session.get(CreationSource, source_id)
    if source is None or source.user_id != user_id or source.trashed_at is not None:
        raise ApiError(404, "ABM_NOT_FOUND", "Source not found.")
    return source


async def trash_source(
    session: AsyncSession,
    user_id: str,
    source_id: str,
    *,
    reason: str = "manual",
    trash_days: int = 10,
) -> CreationSource:
    source = await get_source(session, user_id, source_id)
    now = utcnow()
    source.trashed_at = now
    source.purge_after = now + timedelta(days=max(1, trash_days))
    source.trash_reason = reason
    return source


async def restore_source(
    session: AsyncSession,
    user_id: str,
    source_id: str,
) -> CreationSource:
    source = await session.get(CreationSource, source_id)
    if source is None or source.user_id != user_id or source.trashed_at is None:
        raise ApiError(404, "ABM_NOT_FOUND", "Source not found in the recycle bin.")
    source.trashed_at = None
    source.purge_after = None
    source.trash_reason = None
    source.fetched_at = utcnow()
    return source


async def purge_source(
    session: AsyncSession,
    user_id: str,
    source_id: str,
) -> None:
    source = await session.get(CreationSource, source_id)
    if source is None or source.user_id != user_id or source.trashed_at is None:
        raise ApiError(404, "ABM_NOT_FOUND", "Source not found in the recycle bin.")
    await session.delete(source)


def _remaining_days(purge_after: datetime | None, now: datetime) -> int:
    if purge_after is None:
        return 0
    if purge_after.tzinfo is None:
        purge_after = purge_after.replace(tzinfo=UTC)
    return max(0, (purge_after - now).days)


async def list_trash(
    session: AsyncSession,
    user_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    now = utcnow()
    sources = (
        await session.scalars(
            select(CreationSource)
            .where(
                CreationSource.user_id == user_id,
                CreationSource.trashed_at.is_not(None),
            )
            .order_by(CreationSource.trashed_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    assets = (
        await session.scalars(
            select(CreationAsset)
            .where(
                CreationAsset.user_id == user_id,
                CreationAsset.trashed_at.is_not(None),
            )
            .order_by(CreationAsset.trashed_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items: list[dict[str, Any]] = []
    for asset in assets:
        items.append(
            {
                "type": "asset",
                "id": asset.id,
                "title": asset.title,
                "subtitle": asset.master_platform,
                "reason": asset.trash_reason,
                "trashedAt": asset.trashed_at.isoformat() if asset.trashed_at else None,
                "purgeAfter": asset.purge_after.isoformat() if asset.purge_after else None,
                "remainingDays": _remaining_days(asset.purge_after, now),
            }
        )
    for source in sources:
        items.append(
            {
                "type": "source",
                "id": source.id,
                "title": source.title,
                "subtitle": source.domain,
                "reason": source.trash_reason,
                "trashedAt": source.trashed_at.isoformat() if source.trashed_at else None,
                "purgeAfter": source.purge_after.isoformat() if source.purge_after else None,
                "remainingDays": _remaining_days(source.purge_after, now),
            }
        )
    items.sort(key=lambda item: item["trashedAt"] or "", reverse=True)
    return items


async def empty_trash(session: AsyncSession, user_id: str) -> dict[str, int]:
    assets = (
        await session.scalars(
            select(CreationAsset).where(
                CreationAsset.user_id == user_id,
                CreationAsset.trashed_at.is_not(None),
            )
        )
    ).all()
    for asset in assets:
        await session.execute(
            delete(CreationAssetVersion).where(CreationAssetVersion.asset_id == asset.id)
        )
        await session.delete(asset)
    sources = (
        await session.scalars(
            select(CreationSource).where(
                CreationSource.user_id == user_id,
                CreationSource.trashed_at.is_not(None),
            )
        )
    ).all()
    for source in sources:
        await session.delete(source)
    return {"purgedAssets": len(assets), "purgedSources": len(sources)}


async def count_trash(session: AsyncSession, user_id: str) -> int:
    sources = int(
        await session.scalar(
            select(func.count(CreationSource.id)).where(
                CreationSource.user_id == user_id,
                CreationSource.trashed_at.is_not(None),
            )
        )
        or 0
    )
    assets = int(
        await session.scalar(
            select(func.count(CreationAsset.id)).where(
                CreationAsset.user_id == user_id,
                CreationAsset.trashed_at.is_not(None),
            )
        )
        or 0
    )
    return sources + assets


__all__ = [
    "ACTIVE_STATUSES",
    "JOB_STATUSES",
    "count_active_jobs",
    "count_jobs",
    "count_sources",
    "count_trash",
    "create_job",
    "empty_trash",
    "event_dict",
    "get_job",
    "get_source",
    "job_dict",
    "list_events",
    "list_jobs",
    "list_sources",
    "list_trash",
    "monthly_pages_used",
    "purge_source",
    "restore_source",
    "source_dict",
    "trash_source",
]
