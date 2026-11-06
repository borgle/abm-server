from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...admin.creation_config import load_config
from ...auth.dependencies import AuthContext, get_current_auth, require_csrf
from ...creation import (
    PLATFORMS,
    archive_project,
    count_assets,
    create_asset,
    create_project,
    create_version,
    get_asset,
    list_assets,
    list_projects,
    list_versions,
    project_asset_counts,
    public_asset,
    public_project,
    public_version,
    purge_asset,
    restore_asset,
    trash_asset,
    update_asset,
    update_project,
)
from ...creation import media as media_service
from ...creation import publish as publish_service
from ...creation.generation import generate_draft
from ...creation.research import adapters as research_adapters
from ...creation.research import service as research_service
from ...creation.research.runner import TERMINAL_STATUSES
from ...creation.templates_data import CATEGORIES, template_list
from ...database import get_session
from ...errors import ApiError
from ...extension_gateway import GatewayCallError
from ...models import CreationAssetVersion, CreationResearchJob, utcnow
from ...quotas import quota_policy
from ...schemas import (
    CreationAssetCreate,
    CreationAssetPatch,
    CreationGenerateRequest,
    CreationProjectCreate,
    CreationProjectPatch,
    CreationPublicationCreate,
    CreationPublicationPublish,
    CreationResearchJobCreate,
    CreationResearchResume,
    CreationVersionCreate,
)
from ...tiers import tier_for

router = APIRouter(prefix="/api/v1/creation", tags=["creation"])


@router.get("/platforms")
async def platforms(_auth: AuthContext = Depends(get_current_auth)) -> dict:
    return {"ok": True, "items": PLATFORMS}


@router.get("/projects")
async def projects(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await list_projects(db, auth.user.id)
    counts = await project_asset_counts(db, auth.user.id)
    return {
        "ok": True,
        "items": [public_project(row, counts.get(row.id, 0)) for row in rows],
    }


@router.post("/projects", status_code=201)
async def create_project_route(
    payload: CreationProjectCreate,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    project = await create_project(
        db,
        auth.user,
        title=payload.title,
        description=payload.description,
        default_platform=payload.default_platform,
    )
    await db.commit()
    return {"ok": True, "project": public_project(project)}


@router.patch("/projects/{project_id}")
async def patch_project(
    project_id: str,
    payload: CreationProjectPatch,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    project = await update_project(
        db,
        auth.user.id,
        project_id,
        title=payload.title,
        description=payload.description,
        default_platform=payload.default_platform,
    )
    await db.commit()
    return {"ok": True, "project": public_project(project)}


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> None:
    await archive_project(db, auth.user.id, project_id)
    await db.commit()


@router.get("/assets")
async def assets(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await list_assets(
        db,
        auth.user.id,
        project_id=project_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    total = await count_assets(db, auth.user.id, project_id=project_id, status=status)
    covers = await media_service.cover_map(db, auth.user.id, [row.id for row in rows])
    items = []
    for row in rows:
        item = public_asset(row)
        cover = covers.get(row.id)
        item["coverUrl"] = f"/api/v1/creation/media/{cover.id}/file" if cover is not None else None
        items.append(item)
    return {
        "ok": True,
        "items": items,
        "total": total,
    }


@router.post("/assets", status_code=201)
async def create_asset_route(
    payload: CreationAssetCreate,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    asset = await create_asset(
        db,
        auth.user,
        title=payload.title,
        kind=payload.kind,
        project_id=payload.project_id,
        platform=payload.platform,
        content_md=payload.content_md,
    )
    await db.commit()
    return {"ok": True, "asset": public_asset(asset)}


@router.get("/assets/{asset_id}")
async def asset_detail(
    asset_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    asset = await get_asset(db, auth.user.id, asset_id)
    version = (
        await db.get(CreationAssetVersion, asset.current_version_id)
        if asset.current_version_id
        else None
    )
    return {
        "ok": True,
        "asset": public_asset(asset),
        "version": public_version(version) if version else None,
    }


@router.patch("/assets/{asset_id}")
async def patch_asset(
    asset_id: str,
    payload: CreationAssetPatch,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    asset = await update_asset(
        db,
        auth.user.id,
        asset_id,
        title=payload.title,
        status=payload.status,
        platform=payload.platform,
        tags=payload.tags,
    )
    await db.commit()
    return {"ok": True, "asset": public_asset(asset)}


@router.delete("/assets/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> None:
    await trash_asset(db, auth.user.id, asset_id)
    await db.commit()


@router.get("/assets/{asset_id}/versions")
async def asset_versions(
    asset_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await list_versions(db, auth.user.id, asset_id)
    return {"ok": True, "items": [public_version(row) for row in rows]}


@router.post("/assets/{asset_id}/versions", status_code=201)
async def create_asset_version(
    asset_id: str,
    payload: CreationVersionCreate,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    version = await create_version(
        db,
        auth.user.id,
        asset_id,
        content_md=payload.content_md,
        title=payload.title,
        outline=payload.outline,
        brief=payload.brief,
        citations=payload.citations,
        source_ids=payload.source_ids,
    )
    await db.commit()
    return {"ok": True, "version": public_version(version)}


# -- generation ------------------------------------------------------------


def _generation_payload(result) -> dict:
    return {
        "ok": True,
        "asset": public_asset(result.asset),
        "version": public_version(result.version),
        "citations": result.citations,
        "model": result.model,
        "modelSource": result.model_source,
        "tokens": {"in": result.tokens_in, "out": result.tokens_out},
    }


@router.post("/generate", status_code=201)
async def generate_asset(
    payload: CreationGenerateRequest,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    result = await generate_draft(
        db,
        request.app.state.settings,
        auth.user,
        platform=payload.platform,
        brief=payload.brief,
        source_ids=payload.source_ids,
        project_id=payload.project_id,
        title=payload.title,
    )
    await db.commit()
    return _generation_payload(result)


@router.post("/assets/{asset_id}/generate")
async def generate_asset_version(
    asset_id: str,
    payload: CreationGenerateRequest,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    result = await generate_draft(
        db,
        request.app.state.settings,
        auth.user,
        platform=payload.platform,
        brief=payload.brief,
        source_ids=payload.source_ids,
        asset_id=asset_id,
        title=payload.title,
    )
    await db.commit()
    return _generation_payload(result)


# -- templates -------------------------------------------------------------


@router.get("/templates")
async def templates(_auth: AuthContext = Depends(get_current_auth)) -> dict:
    return {"ok": True, "categories": CATEGORIES, "items": template_list()}


# -- research -------------------------------------------------------------


@router.post("/research/diagnostics")
async def research_diagnostics(
    request: Request,
    auth: AuthContext = Depends(require_csrf),
) -> dict:
    """Check the browser connection and a minimal tool round trip."""
    gateway = request.app.state.extension_gateway
    session_id = f"creation-diag-{uuid4().hex}"
    try:
        tenant_context = {
            "taskId": session_id,
            "groupTitle": "ABM · 诊断",
            "collapsed": False,
        }
        connection_id = await gateway.acquire_connection_for_session(
            user_id=auth.user.id,
            session_id=session_id,
            ttl_seconds=60,
            group_title="ABM · 诊断",
            collapsed=False,
        )
    except GatewayCallError as exc:
        return {
            "ok": False,
            "stage": "connect",
            "code": exc.code,
            "message": exc.message,
        }
    try:
        await gateway.call_tool(
            connection_id=connection_id,
            name="browser_navigate",
            context=tenant_context,
            arguments={
                "url": "https://www.bing.com/",
                "waitUntil": "domcontentloaded",
                "timeout": 20000,
                "reuseKey": "creation-diagnostic",
            },
            timeout_ms=30000,
        )
        page = await gateway.call_tool(
            connection_id=connection_id,
            name="browser_inject_script",
            context=tenant_context,
            arguments={
                "code": "return { title: document.title, url: location.href };",
                "args": {},
            },
            timeout_ms=20000,
        )
    except GatewayCallError as exc:
        return {
            "ok": False,
            "stage": "tool",
            "code": exc.code,
            "message": exc.message,
        }
    finally:
        await gateway.release_session(auth.user.id, session_id)
    return {
        "ok": True,
        "stage": "done",
        "page": research_adapters.parse_tool_result(page),
    }


def _runner(request: Request):
    return request.app.state.research_runner


@router.get("/research/jobs")
async def research_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await research_service.list_jobs(
        db, auth.user.id, status=status, limit=limit, offset=offset
    )
    total = await research_service.count_jobs(db, auth.user.id, status=status)
    return {
        "ok": True,
        "items": [research_service.job_dict(row) for row in rows],
        "total": total,
    }


@router.post("/research/jobs", status_code=201)
async def create_research_job(
    payload: CreationResearchJobCreate,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    config = await load_config(db)
    limit = 2 if tier_for(auth.user, request.app.state.settings) == "pro" else 1
    active = await research_service.count_active_jobs(db, auth.user.id)
    if active >= limit:
        raise ApiError(
            409,
            "ABM_CREATION_JOB_LIMIT",
            "Too many research jobs are already running.",
            retryable=True,
            action="wait",
        )
    job = await research_service.create_job(
        db,
        auth.user,
        keywords=payload.keywords,
        exclusions=payload.exclusions,
        engines=payload.engines or None,
        depth=payload.depth,
        language=payload.language,
        project_id=payload.project_id,
        config=config,
        limits=await quota_policy(request.app.state.settings).limits(db, auth.user, config),
    )
    await db.commit()
    _runner(request).launch(job.id)
    return {"ok": True, "job": research_service.job_dict(job)}


@router.get("/research/jobs/{job_id}")
async def research_job(
    job_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    job = await research_service.get_job(db, auth.user.id, job_id)
    sources = await research_service.list_sources(db, auth.user.id, job_id=job_id, limit=50)
    events = await research_service.list_events(db, auth.user.id, job_id, after_seq=0, limit=100)
    return {
        "ok": True,
        "job": research_service.job_dict(job),
        "sources": [research_service.source_dict(item) for item in sources],
        "events": [research_service.event_dict(item) for item in events],
    }


@router.post("/research/jobs/{job_id}/pause")
async def pause_research_job(
    job_id: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    job = await research_service.get_job(db, auth.user.id, job_id)
    if job.status not in {"queued", "running"}:
        raise ApiError(409, "ABM_VALIDATION_ERROR", "Only a running job can be paused.")
    await _runner(request).pause(job.id)
    return {"ok": True, "job": research_service.job_dict(job)}


@router.post("/research/jobs/{job_id}/resume")
async def resume_research_job(
    job_id: str,
    request: Request,
    payload: CreationResearchResume | None = None,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    job = await research_service.get_job(db, auth.user.id, job_id)
    if job.status not in {"paused", "needs_attention", "interrupted"}:
        raise ApiError(409, "ABM_VALIDATION_ERROR", "This job cannot be resumed.")
    await _runner(request).resume(
        job.id,
        skip_engine=payload.skip_engine if payload else None,
        skip_current=payload.skip_current if payload else False,
    )
    refreshed = await research_service.get_job(db, auth.user.id, job_id)
    return {"ok": True, "job": research_service.job_dict(refreshed)}


@router.post("/research/jobs/{job_id}/cancel")
async def cancel_research_job(
    job_id: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    job = await research_service.get_job(db, auth.user.id, job_id)
    if job.status in TERMINAL_STATUSES:
        return {"ok": True, "job": research_service.job_dict(job)}
    _runner(request).cancel(job.id)
    job.status = "cancelled"
    job.finished_at = utcnow()
    job.updated_at = utcnow()
    db.add(job)
    await db.commit()
    return {"ok": True, "job": research_service.job_dict(job)}


@router.get("/research/jobs/{job_id}/events")
async def research_job_events(
    job_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    await research_service.get_job(db, auth.user.id, job_id)
    header = request.headers.get("last-event-id")
    start = after
    if header and header.isdigit():
        start = max(start, int(header))
    database = request.app.state.database
    user_id = auth.user.id

    async def stream() -> AsyncIterator[str]:
        cursor = start
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 900
        while True:
            if await request.is_disconnected():
                return
            async with database.sessions() as session:
                events = await research_service.list_events(
                    session, user_id, job_id, after_seq=cursor, limit=200
                )
                current = await session.get(CreationResearchJob, job_id)
                status = current.status if current is not None else "failed"
            for event in events:
                cursor = event.seq
                payload = research_service.event_dict(event)
                yield (
                    f"id: {event.seq}\nevent: job\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
            if status in TERMINAL_STATUSES:
                yield "event: done\ndata: {}\n\n"
                return
            if not events:
                yield ": keepalive\n\n"
            if loop.time() > deadline:
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# -- sources ---------------------------------------------------------------


@router.get("/sources")
async def sources(
    q: str | None = Query(default=None, max_length=200),
    domain: str | None = Query(default=None, max_length=255),
    job_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await research_service.list_sources(
        db,
        auth.user.id,
        query_text=q,
        domain=domain,
        job_id=job_id,
        limit=limit,
        offset=offset,
    )
    total = await research_service.count_sources(
        db, auth.user.id, query_text=q, domain=domain, job_id=job_id
    )
    return {
        "ok": True,
        "items": [research_service.source_dict(row) for row in rows],
        "total": total,
    }


@router.get("/sources/{source_id}")
async def source_detail(
    source_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    source = await research_service.get_source(db, auth.user.id, source_id)
    return {
        "ok": True,
        "source": research_service.source_dict(source, include_content=True),
    }


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> None:
    config = await load_config(db)
    await research_service.trash_source(
        db,
        auth.user.id,
        source_id,
        trash_days=int(config.get("trashDays") or 10),
    )
    await db.commit()


@router.post("/sources/{source_id}/restore")
async def restore_source(
    source_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    source = await research_service.restore_source(db, auth.user.id, source_id)
    await db.commit()
    return {"ok": True, "source": research_service.source_dict(source)}


@router.delete("/sources/{source_id}/purge", status_code=204)
async def purge_source(
    source_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> None:
    await research_service.purge_source(db, auth.user.id, source_id)
    await db.commit()


# -- publishing ------------------------------------------------------------


@router.get("/publish/targets")
async def publish_targets(_auth: AuthContext = Depends(get_current_auth)) -> dict:
    return {
        "ok": True,
        "items": [{"id": key, **value} for key, value in publish_service.PUBLISH_TARGETS.items()],
    }


@router.get("/publish/tasks")
async def publish_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await publish_service.list_publications(db, auth.user.id, limit=limit, offset=offset)
    total = await publish_service.count_publications(db, auth.user.id)
    return {
        "ok": True,
        "items": [publish_service.publication_dict(row) for row in rows],
        "total": total,
    }


@router.post("/publish/tasks", status_code=201)
async def create_publish_task(
    payload: CreationPublicationCreate,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    publication = await publish_service.create_publication(
        db,
        auth.user,
        asset_id=payload.asset_id,
        platform=payload.platform,
    )
    await db.commit()
    return {"ok": True, "task": publish_service.publication_dict(publication)}


@router.get("/publish/tasks/{task_id}")
async def publish_task(
    task_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    item = await publish_service.get_publication(db, auth.user.id, task_id)
    return {"ok": True, "task": publish_service.publication_dict(item, include_body=True)}


@router.post("/publish/tasks/{task_id}/open")
async def open_publish_task(
    task_id: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    item = await publish_service.get_publication(db, auth.user.id, task_id)
    item = await publish_service.open_publication(
        db, request.app.state.extension_gateway, auth.user, item
    )
    await db.commit()
    return {"ok": True, "task": publish_service.publication_dict(item)}


@router.post("/publish/tasks/{task_id}/close")
async def close_publish_task(
    task_id: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    item = await publish_service.get_publication(db, auth.user.id, task_id)
    item = await publish_service.close_publication(
        db, request.app.state.extension_gateway, auth.user, item
    )
    await db.commit()
    return {"ok": True, "task": publish_service.publication_dict(item)}


@router.post("/publish/tasks/{task_id}/published")
async def mark_publish_task_published(
    task_id: str,
    payload: CreationPublicationPublish,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    item = await publish_service.get_publication(db, auth.user.id, task_id)
    item = await publish_service.mark_published(
        db,
        request.app.state.extension_gateway,
        auth.user,
        item,
        published_url=payload.url,
    )
    await db.commit()
    return {"ok": True, "task": publish_service.publication_dict(item)}


# -- recycle bin -----------------------------------------------------------


@router.get("/trash")
async def recycle_bin(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items = await research_service.list_trash(db, auth.user.id, limit=limit, offset=offset)
    total = await research_service.count_trash(db, auth.user.id)
    return {"ok": True, "items": items, "total": total}


@router.post("/trash/empty")
async def empty_recycle_bin(
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    result = await research_service.empty_trash(db, auth.user.id)
    await db.commit()
    return {"ok": True, **result}


@router.post("/assets/{asset_id}/restore")
async def restore_asset_route(
    asset_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    asset = await restore_asset(db, auth.user.id, asset_id)
    await db.commit()
    return {"ok": True, "asset": public_asset(asset)}


@router.delete("/assets/{asset_id}/purge", status_code=204)
async def purge_asset_route(
    asset_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> None:
    await purge_asset(db, auth.user.id, asset_id)
    await db.commit()


__all__ = ["router"]
