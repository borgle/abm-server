"""API routes for creation media and layout exports."""

from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...admin.creation_config import load_config
from ...auth.dependencies import AuthContext, get_current_auth, require_csrf
from ...creation import exports as export_service
from ...creation import media as media_service
from ...creation.service import get_asset
from ...database import get_session
from ...errors import ApiError
from ...models import CreationExport, CreationMedia, User, utcnow
from ...schemas import (
    CreationExportCreate,
    CreationMediaGenerateRequest,
    CreationMediaPatch,
)
from ...storage import StorageError

router = APIRouter(prefix="/api/v1/creation", tags=["creation"])

_MEDIA_REF = re.compile(r"/api/v1/creation/media/([0-9a-fA-F-]{36})/file")


def _storage(request: Request):
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise ApiError(
            503,
            "ABM_CREATION_STORAGE_UNAVAILABLE",
            "Media storage is not configured.",
            retryable=False,
            action="contact_admin",
        )
    return storage


async def _export(request: Request, db: AsyncSession, user: User, export_id: str) -> CreationExport:
    export = await db.get(CreationExport, export_id)
    if export is None or export.user_id != user.id:
        raise ApiError(404, "ABM_NOT_FOUND", "Export not found.")
    if export.expires_at is not None:
        expires = export.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= utcnow():
            raise ApiError(
                410,
                "ABM_CREATION_EXPORT_EXPIRED",
                "This export has expired. Render it again.",
                retryable=True,
                action="retry",
            )
    return export


@router.get("/image-presets")
async def image_presets(_auth: AuthContext = Depends(get_current_auth)) -> dict:
    return {
        "ok": True,
        "sizes": media_service.PLATFORM_SIZES,
        "covers": {
            platform: {"width": size[0], "height": size[1]}
            for platform, size in media_service.PLATFORM_COVERS.items()
        },
        "styles": {
            "wechat_html": ["default"],
            "xhs_cards": ["xhs-paper", "xhs-ink", "xhs-grid"],
        },
    }


@router.post("/assets/{asset_id}/media/generate", status_code=201)
async def generate_media_route(
    asset_id: str,
    payload: CreationMediaGenerateRequest,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    asset = await get_asset(db, auth.user.id, asset_id)
    rows = await media_service.generate_media(
        db,
        request.app.state.settings,
        _storage(request),
        auth.user,
        asset,
        kind=payload.kind,
        platform=payload.platform,
        prompt=payload.prompt,
        negative_prompt=payload.negative_prompt,
        n=payload.n,
        size=payload.size,
        asset_version_id=payload.asset_version_id,
        reference_media_id=payload.reference_media_id,
    )
    await db.commit()
    return {
        "ok": True,
        "items": [media_service.media_dict(row) for row in rows],
    }


@router.get("/assets/{asset_id}/media")
async def list_media_route(
    asset_id: str,
    include_trashed: bool = Query(default=False),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await get_asset(db, auth.user.id, asset_id)
    rows = await media_service.list_media(
        db, auth.user.id, asset_id=asset_id, include_trashed=include_trashed
    )
    return {"ok": True, "items": [media_service.media_dict(row) for row in rows]}


@router.get("/media/{media_id}")
async def get_media_route(
    media_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    media = await media_service.get_media(db, auth.user.id, media_id)
    return {"ok": True, "item": media_service.media_dict(media)}


@router.get("/media/{media_id}/file")
async def media_file_route(
    media_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> Response:
    media = await media_service.get_media(db, auth.user.id, media_id)
    try:
        data = await _storage(request).get(media.storage_key)
    except StorageError as exc:
        raise ApiError(
            404,
            "ABM_NOT_FOUND",
            "Media file is missing from storage.",
            retryable=False,
            action="contact_admin",
        ) from exc
    return Response(
        content=data,
        media_type=media.mime,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.patch("/media/{media_id}")
async def patch_media_route(
    media_id: str,
    payload: CreationMediaPatch,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    media = await media_service.update_media(
        db, auth.user.id, media_id, role=payload.role, kind=payload.kind
    )
    await db.commit()
    return {"ok": True, "item": media_service.media_dict(media)}


@router.delete("/media/{media_id}", status_code=202)
async def trash_media_route(
    media_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    config = await load_config(db)
    media = await media_service.trash_media(
        db,
        auth.user.id,
        media_id,
        trash_days=int(config.get("trashDays") or 10),
    )
    await db.commit()
    return {"ok": True, "item": media_service.media_dict(media)}


@router.post("/media/{media_id}/restore")
async def restore_media_route(
    media_id: str,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    media = await media_service.restore_media(db, auth.user.id, media_id)
    await db.commit()
    return {"ok": True, "item": media_service.media_dict(media)}


@router.post("/assets/{asset_id}/exports", status_code=201)
async def create_export_route(
    asset_id: str,
    payload: CreationExportCreate,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    asset = await get_asset(db, auth.user.id, asset_id)
    export = await export_service.create_export(
        db,
        request.app.state.settings,
        _storage(request),
        auth.user,
        asset,
        target=payload.target,
        style_id=payload.style_id,
        options=payload.options,
    )
    await db.commit()
    return {"ok": True, "item": export_service.export_dict(export)}


@router.get("/exports/{export_id}")
async def get_export_route(
    export_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    export = await _export(request, db, auth.user, export_id)
    return {"ok": True, "item": export_service.export_dict(export)}


@router.delete("/exports/{export_id}", status_code=204)
async def delete_export_route(
    export_id: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Response:
    export = await _export(request, db, auth.user, export_id)
    if export.file_key:
        from contextlib import suppress

        with suppress(StorageError):
            await _storage(request).delete(export.file_key)
    await db.delete(export)
    await db.commit()
    return Response(status_code=204)


@router.get("/exports/{export_id}/file")
async def export_file_route(
    export_id: str,
    request: Request,
    format: str = Query(default="auto"),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> Response:
    export = await _export(request, db, auth.user, export_id)
    storage = _storage(request)

    if export.target == "wechat_html" and format != "zip":
        try:
            data = await storage.get(export.file_key or "")
        except StorageError as exc:
            raise ApiError(
                404,
                "ABM_NOT_FOUND",
                "The export file is missing.",
                retryable=False,
                action="retry",
            ) from exc
        return Response(
            content=data,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="abm-export-{export.id[:8]}.html"',
            },
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if export.target == "wechat_html":
            try:
                html = await storage.get(export.file_key or "")
            except StorageError as exc:
                raise ApiError(404, "ABM_NOT_FOUND", "The export file is missing.") from exc
            archive.writestr("export.html", html)
            for item in export.files or []:
                src = str(item.get("src") or "")
                match = _MEDIA_REF.search(src)
                if not match:
                    continue
                media = await db.get(CreationMedia, match.group(1))
                if media is None or media.user_id != auth.user.id:
                    continue
                try:
                    payload = await storage.get(media.storage_key)
                except StorageError:
                    continue
                suffix = media.mime.split("/")[-1].replace("jpeg", "jpg")
                archive.writestr(f"image-{int(item.get('index') or 0):02d}.{suffix}", payload)
        else:
            for item in export.files or []:
                media_id = item.get("mediaId")
                if not media_id:
                    continue
                media = await db.get(CreationMedia, media_id)
                if media is None or media.user_id != auth.user.id:
                    continue
                try:
                    payload = await storage.get(media.storage_key)
                except StorageError:
                    continue
                archive.writestr(f"card-{int(item.get('page') or 0):02d}.png", payload)

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="abm-export-{export.id[:8]}.zip"',
        },
    )
