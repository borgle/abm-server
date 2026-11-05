"""Layout exports: WeChat HTML and Xiaohongshu cards."""

from __future__ import annotations

import base64
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..admin.creation_config import load_config
from ..config import Settings
from ..errors import ApiError
from ..models import (
    CreationAsset,
    CreationAssetVersion,
    CreationExport,
    CreationMedia,
    User,
    utcnow,
)
from ..storage import ObjectStorage, digest, export_key, media_key
from .layout import parse_blocks, render_wechat
from .media import storage_used
from ..quotas import quota_policy
from .render import CardDocument, render_cards

TARGETS = {"wechat_html", "xhs_cards"}
STYLES = {"wechat": {"default"}, "xhs_cards": {"default", "xhs-paper", "xhs-ink", "xhs-grid"}}

_MEDIA_REF = re.compile(r"/api/v1/creation/media/([0-9a-fA-F-]{36})/file")


def _mime_suffix(mime: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }.get(mime, "bin")


async def _current_version(
    session: AsyncSession, asset: CreationAsset
) -> CreationAssetVersion:
    if not asset.current_version_id:
        raise ApiError(
            409,
            "ABM_CREATION_EMPTY_ASSET",
            "This asset has no saved version to export.",
            retryable=False,
            action="save_version",
        )
    version = await session.get(CreationAssetVersion, asset.current_version_id)
    if version is None or version.asset_id != asset.id:
        raise ApiError(404, "ABM_NOT_FOUND", "Asset version not found.")
    return version


async def _media_for_src(
    session: AsyncSession,
    storage: ObjectStorage,
    user_id: str,
    src: str,
) -> tuple[bytes, str] | None:
    match = _MEDIA_REF.search(src or "")
    if not match:
        return None
    media = await session.get(CreationMedia, match.group(1))
    if media is None or media.user_id != user_id or not media.storage_key:
        return None
    return await storage.get(media.storage_key), media.mime


async def _cover_data_uri(
    session: AsyncSession,
    storage: ObjectStorage,
    user_id: str,
    asset_id: str,
) -> str:
    cover = await session.scalar(
        select(CreationMedia)
        .where(
            CreationMedia.user_id == user_id,
            CreationMedia.asset_id == asset_id,
            CreationMedia.role == "cover",
            CreationMedia.trashed_at.is_(None),
        )
        .order_by(CreationMedia.created_at.desc())
        .limit(1)
    )
    if cover is None:
        return ""
    data = await storage.get(cover.storage_key)
    return f"data:{cover.mime};base64,{base64.b64encode(data).decode('ascii')}"


async def create_export(
    session: AsyncSession,
    settings: Settings,
    storage: ObjectStorage,
    user: User,
    asset: CreationAsset,
    *,
    target: str,
    style_id: str = "default",
    options: dict[str, Any] | None = None,
) -> CreationExport:
    if target not in TARGETS:
        raise ApiError(422, "ABM_VALIDATION", "Unknown export target.")
    version = await _current_version(session, asset)
    config = await load_config(session)
    limits = await quota_policy(settings).limits(session, user, config)
    limit = limits.storage_bytes
    used = await storage_used(session, user.id)

    blocks = parse_blocks(version.content_md)
    if not blocks:
        raise ApiError(
            409,
            "ABM_CREATION_EMPTY_ASSET",
            "This asset has no content to export.",
            retryable=False,
            action="edit",
        )

    export = CreationExport(
        user_id=user.id,
        asset_id=asset.id,
        asset_version_id=version.id,
        target=target,
        style_id=style_id,
        status="pending",
        options=options or {},
        files=[],
        created_at=utcnow(),
    )
    session.add(export)
    await session.flush()

    expires_at = utcnow().replace(microsecond=0)
    export.expires_at = expires_at + timedelta(days=max(1, settings.export_retention_days))

    if target == "wechat_html":
        document, images = render_wechat(asset.title, blocks)
        payload = document.encode("utf-8")
        if limit and used + len(payload) > limit:
            raise ApiError(
                413,
                "ABM_CREATION_STORAGE_FULL",
                "The asset storage for this plan is full.",
                retryable=False,
                action="upgrade",
            )
        key = export_key(user.id, export.id, "export.html")
        stored = await storage.put(key, payload, content_type="text/html; charset=utf-8")
        export.file_key = stored.key
        export.file_bytes = stored.size
        export.files = [{"index": item["index"], "src": item["src"], "alt": item["alt"]} for item in images]
        export.status = "ready"
        return export

    # Xiaohongshu cards
    for block in blocks:
        if block.type != "image" or not block.src:
            continue
        local = await _media_for_src(session, storage, user.id, block.src)
        if local is not None:
            data, mime = local
            block.src = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

    style = style_id if style_id in STYLES["xhs_cards"] else "xhs-paper"
    document = CardDocument(
        title=asset.title,
        subtitle=str((options or {}).get("subtitle") or ""),
        blocks=blocks,
        style_id=style,
        include_cover=bool((options or {}).get("includeCover", True)),
        show_page_number=bool((options or {}).get("showPageNumber", True)),
        cover_image=await _cover_data_uri(session, storage, user.id, asset.id),
    )
    shots = await render_cards(document, no_sandbox=settings.render_no_sandbox)
    if not shots:
        raise ApiError(
            502,
            "ABM_CREATION_RENDER_UNAVAILABLE",
            "The renderer produced no cards.",
            retryable=True,
            action="retry",
        )

    total = sum(len(shot) for shot in shots)
    if limit and used + total > limit:
        raise ApiError(
            413,
            "ABM_CREATION_STORAGE_FULL",
            "The asset storage for this plan is full.",
            retryable=False,
            action="upgrade",
        )

    files: list[dict[str, Any]] = []
    for page, shot in enumerate(shots, start=1):
        sha = digest(shot)
        existing = await session.scalar(
            select(CreationMedia).where(
                CreationMedia.user_id == user.id,
                CreationMedia.sha256 == sha,
                CreationMedia.trashed_at.is_(None),
            )
        )
        if existing is not None:
            files.append({"page": page, "mediaId": existing.id})
            continue
        key = media_key(user.id, sha, "png")
        stored = await storage.put(key, shot, content_type="image/png")
        media = CreationMedia(
            user_id=user.id,
            project_id=asset.project_id,
            asset_id=asset.id,
            asset_version_id=version.id,
            kind="card",
            platform=asset.master_platform or "xiaohongshu",
            role="rendered",
            status="ready",
            prompt="",
            provider_id=None,
            model=f"layout:{style}",
            width=1080,
            height=1440,
            mime="image/png",
            storage_key=stored.key,
            bytes=stored.size,
            sha256=sha,
            meta={"style": style, "page": page},
        )
        session.add(media)
        await session.flush()
        files.append({"page": page, "mediaId": media.id})

    export.files = files
    export.file_bytes = total
    export.status = "ready"
    return export


def export_dict(export: CreationExport, *, base_url: str = "") -> dict[str, Any]:
    prefix = base_url.rstrip("/")
    files = []
    for item in export.files or []:
        if item.get("mediaId"):
            files.append(
                {
                    "page": item.get("page"),
                    "mediaId": item["mediaId"],
                    "url": f"{prefix}/api/v1/creation/media/{item['mediaId']}/file",
                }
            )
        else:
            files.append({"index": item.get("index"), "src": item.get("src"), "alt": item.get("alt")})
    return {
        "id": export.id,
        "assetId": export.asset_id,
        "assetVersionId": export.asset_version_id,
        "target": export.target,
        "styleId": export.style_id,
        "status": export.status,
        "files": files,
        "downloadUrl": f"{prefix}/api/v1/creation/exports/{export.id}/file",
        "errorCode": export.error_code,
        "errorMessage": export.error_message,
        "createdAt": export.created_at.isoformat(),
        "expiresAt": export.expires_at.isoformat() if export.expires_at else None,
    }
