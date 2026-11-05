"""Browser-assisted publishing tasks.

Publishing is intentionally assistive: ABM opens the platform editor in a
high-priority, foreground tab group, keeps the content snapshot for copying,
and never clicks the final publish button.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..extension_gateway import GatewayCallError
from ..models import (
    CreationAssetVersion,
    CreationPublication,
    User,
    utcnow,
)
from .service import get_asset

PUBLISH_TARGETS: dict[str, dict[str, Any]] = {
    "xiaohongshu": {
        "label": "小红书",
        "editorUrl": "https://creator.xiaohongshu.com/publish/publish",
    },
    "wechat": {"label": "公众号", "editorUrl": "https://mp.weixin.qq.com/"},
    "zhihu": {"label": "知乎", "editorUrl": "https://zhuanlan.zhihu.com/write"},
    "shipinhao": {
        "label": "视频号",
        "editorUrl": "https://channels.weixin.qq.com/platform/post/create",
    },
}


def publication_dict(item: CreationPublication, *, include_body: bool = False) -> dict[str, Any]:
    payload = {
        "id": item.id,
        "assetId": item.asset_id,
        "platform": item.platform,
        "platformLabel": PUBLISH_TARGETS.get(item.platform, {}).get("label", item.platform),
        "status": item.status,
        "title": item.title,
        "targetUrl": item.target_url,
        "publishedUrl": item.published_url,
        "errorCode": item.error_code,
        "errorMessage": item.error_message,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
        "openedAt": item.opened_at.isoformat() if item.opened_at else None,
        "closedAt": item.closed_at.isoformat() if item.closed_at else None,
        "hasSession": bool(item.browser_session_id),
    }
    if include_body:
        payload["body"] = item.body
    return payload


async def create_publication(
    session: AsyncSession,
    user: User,
    *,
    asset_id: str,
    platform: str,
) -> CreationPublication:
    target = PUBLISH_TARGETS.get(platform)
    if target is None:
        raise ApiError(422, "ABM_VALIDATION_ERROR", "Unknown publishing platform.")
    asset = await get_asset(session, user.id, asset_id)
    version = (
        await session.get(CreationAssetVersion, asset.current_version_id)
        if asset.current_version_id
        else None
    )
    publication = CreationPublication(
        user_id=user.id,
        asset_id=asset.id,
        platform=platform,
        status="queued",
        title=asset.title,
        body=version.content_md if version else "",
        target_url=target["editorUrl"],
    )
    session.add(publication)
    await session.flush()
    return publication


async def list_publications(
    session: AsyncSession,
    user_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[CreationPublication]:
    query = (
        select(CreationPublication)
        .where(CreationPublication.user_id == user_id)
        .order_by(CreationPublication.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(query)).all())


async def count_publications(session: AsyncSession, user_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count(CreationPublication.id)).where(CreationPublication.user_id == user_id)
        )
        or 0
    )


async def get_publication(
    session: AsyncSession, user_id: str, publication_id: str
) -> CreationPublication:
    item = await session.get(CreationPublication, publication_id)
    if item is None or item.user_id != user_id:
        raise ApiError(404, "ABM_NOT_FOUND", "Publishing task not found.")
    return item


async def open_publication(
    session: AsyncSession,
    gateway: Any,
    user: User,
    publication: CreationPublication,
) -> CreationPublication:
    if publication.status in {"ready", "published", "closed"}:
        return publication
    target = PUBLISH_TARGETS.get(publication.platform)
    if target is None:
        raise ApiError(422, "ABM_VALIDATION_ERROR", "Unknown publishing platform.")

    browser_session_id = f"pub_{uuid4().hex}"
    group_title = f"ABM · 发布 · {target['label']}"
    publication.status = "opening"
    publication.error_code = None
    publication.error_message = None
    publication.updated_at = utcnow()
    await session.flush()
    # Release the write lock before the browser call: it can take up to the
    # navigation timeout, and holding SQLite's writer lock that long makes every
    # other request fail with "database is locked".
    await session.commit()

    try:
        connection_id = await gateway.acquire_connection_for_session(
            user_id=user.id,
            session_id=browser_session_id,
            priority=100,
            group_title=group_title,
            collapsed=False,
            ttl_seconds=60 * 60,
        )
        context = gateway.session_context(user.id, browser_session_id) or {
            "taskId": browser_session_id,
            "groupTitle": group_title,
            "collapsed": False,
        }
        await gateway.call_tool(
            connection_id=connection_id,
            name="browser_navigate",
            arguments={
                "url": target["editorUrl"],
                "waitUntil": "domcontentloaded",
                "timeout": 45_000,
                "reuseKey": f"publish-{publication.id}",
                "background": False,
            },
            context=context,
        )
    except GatewayCallError as exc:
        await gateway.release_session(user.id, browser_session_id)
        publication.status = (
            "needs_attention"
            if exc.retryable and exc.action in {"open_extension", "wait", "reauthenticate"}
            else "failed"
        )
        publication.error_code = exc.code
        publication.error_message = exc.message
        publication.updated_at = utcnow()
        await session.flush()
        return publication

    publication.status = "ready"
    publication.browser_session_id = browser_session_id
    publication.connection_id = connection_id
    publication.target_url = target["editorUrl"]
    publication.opened_at = utcnow()
    publication.updated_at = utcnow()
    await session.flush()
    return publication


async def close_publication(
    session: AsyncSession,
    gateway: Any,
    user: User,
    publication: CreationPublication,
    *,
    status: str = "closed",
) -> CreationPublication:
    browser_session_id = publication.browser_session_id
    if browser_session_id:
        context = gateway.session_context(user.id, browser_session_id)
        if context is not None:
            with contextlib.suppress(GatewayCallError):
                await gateway.call_tool(
                    connection_id=context["connectionId"],
                    name="browser_control",
                    arguments={"action": "close_group", "params": {}},
                    context=context,
                )
        await gateway.release_session(user.id, browser_session_id)
    publication.browser_session_id = None
    publication.connection_id = None
    publication.status = status
    publication.closed_at = utcnow()
    publication.updated_at = utcnow()
    await session.flush()
    return publication


async def mark_published(
    session: AsyncSession,
    gateway: Any,
    user: User,
    publication: CreationPublication,
    *,
    published_url: str | None,
) -> CreationPublication:
    publication.published_url = published_url
    return await close_publication(session, gateway, user, publication, status="published")


__all__ = [
    "PUBLISH_TARGETS",
    "close_publication",
    "count_publications",
    "create_publication",
    "get_publication",
    "list_publications",
    "mark_published",
    "open_publication",
    "publication_dict",
]
