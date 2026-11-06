"""Creation media: image generation, storage and trash handling."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..admin.creation_config import decrypt_secret, load_config
from ..config import Settings
from ..errors import ApiError
from ..models import CreationAsset, CreationExport, CreationMedia, User, utcnow
from ..quotas import Limits, quota_policy
from ..storage import ObjectStorage, digest, media_key
from .bindings import resolve_image
from .images import ImageProvider, build_openai_images_provider

PLATFORM_SIZES = {
    "xiaohongshu": "1024x1536",
    "wechat": "1536x1024",
    "zhihu": "1536x1024",
    "shipinhao": "1536x1024",
    "master": "1024x1024",
}

PLATFORM_COVERS = {
    "xiaohongshu": (1080, 1440),
    "wechat": (900, 383),
    "zhihu": (1200, 675),
    "shipinhao": (1080, 1260),
    "master": (1080, 1080),
}

MIME_SUFFIX = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

MAX_PROMPT_CHARS = 2000


def provider_size_for(width: int, height: int) -> str:
    """Pick the closest size the model understands, then crop to exact."""

    ratio = width / height if height else 1.0
    if ratio >= 1.3:
        return "1536x1024"
    if ratio <= 0.85:
        return "1024x1536"
    return "1024x1024"


def normalize_cover(data: bytes, size: tuple[int, int]) -> bytes:
    """Center-crop and resize to the exact platform cover size."""

    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - pillow is a core dependency
        raise ApiError(
            500,
            "ABM_CREATION_IMAGE_FAILED",
            "Pillow is required to resize covers.",
            retryable=False,
            action="contact_admin",
        ) from exc
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = source.convert("RGB")
            fitted = ImageOps.fit(image, size, method=Image.LANCZOS, centering=(0.5, 0.5))
            buffer = io.BytesIO()
            fitted.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise ApiError(
            502,
            "ABM_CREATION_IMAGE_FAILED",
            f"The generated image could not be resized: {exc}",
            retryable=True,
            action="retry",
        ) from exc


MEDIA_ERROR_TEXT = {
    "ABM_CREATION_IMAGE_NOT_CONFIGURED": "No image model is bound to this plan.",
    "ABM_CREATION_IMAGE_AUTH": "The image provider rejected the API key.",
}


@dataclass(slots=True)
class ImageTarget:
    provider_id: str
    model: str
    provider: ImageProvider


def _day_start() -> datetime:
    now = datetime.now(utcnow().tzinfo)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def resolve_image_target(
    session: AsyncSession,
    config: dict[str, Any],
    user: User,
    *,
    settings: Settings,
    transport: Any | None = None,
) -> ImageTarget:
    provider_id, model = await resolve_image(session, config, settings, user)
    provider = next(
        (item for item in config.get("providers", []) if item.get("id") == provider_id),
        None,
    )
    if provider is None or not provider.get("apiKeyCiphertext"):
        raise ApiError(
            409,
            "ABM_CREATION_IMAGE_NOT_CONFIGURED",
            "The configured image provider no longer exists.",
            retryable=False,
            action="contact_admin",
        )
    adapter = str(provider.get("adapter") or "openai-images")
    if adapter != "openai-images":
        raise ApiError(
            409,
            "ABM_CREATION_IMAGE_ADAPTER_UNSUPPORTED",
            f"Image adapter {adapter!r} is not supported yet.",
            retryable=False,
            action="contact_admin",
        )
    api_key = decrypt_secret(settings, provider["apiKeyCiphertext"])
    return ImageTarget(
        provider_id=provider_id,
        model=model,
        provider=build_openai_images_provider(
            base_url=str(provider.get("baseUrl") or ""),
            api_key=api_key,
            model=model,
            transport=transport,
        ),
    )


async def storage_used(session: AsyncSession, user_id: str) -> int:
    media = await session.scalar(
        select(func.coalesce(func.sum(CreationMedia.bytes), 0)).where(
            CreationMedia.user_id == user_id
        )
    )
    exports = await session.scalar(
        select(func.coalesce(func.sum(CreationExport.file_bytes), 0)).where(
            CreationExport.user_id == user_id
        )
    )
    return int(media or 0) + int(exports or 0)


async def assert_image_quota(
    session: AsyncSession,
    user: User,
    limits: Limits,
    *,
    incoming_bytes: int,
) -> None:
    daily_limit = limits.images_per_day
    if daily_limit:
        used = await session.scalar(
            select(func.count())
            .select_from(CreationMedia)
            .where(
                CreationMedia.user_id == user.id,
                CreationMedia.provider_id.is_not(None),
                CreationMedia.created_at >= _day_start(),
            )
        )
        if int(used or 0) >= daily_limit:
            raise ApiError(
                429,
                "ABM_CREATION_IMAGE_QUOTA",
                "The daily image generation limit for this plan is reached.",
                retryable=True,
                action="upgrade",
            )

    storage_limit = limits.storage_bytes
    if storage_limit:
        used_bytes = await storage_used(session, user.id)
        if used_bytes + incoming_bytes > storage_limit:
            raise ApiError(
                413,
                "ABM_CREATION_STORAGE_FULL",
                "The asset storage for this plan is full.",
                retryable=False,
                action="upgrade",
            )


def media_dict(media: CreationMedia, *, base_url: str = "") -> dict[str, Any]:
    prefix = base_url.rstrip("/")
    return {
        "id": media.id,
        "assetId": media.asset_id,
        "assetVersionId": media.asset_version_id,
        "kind": media.kind,
        "platform": media.platform,
        "role": media.role,
        "status": media.status,
        "prompt": media.prompt,
        "negativePrompt": media.negative_prompt,
        "providerId": media.provider_id,
        "model": media.model,
        "width": media.width,
        "height": media.height,
        "mime": media.mime,
        "bytes": media.bytes,
        "url": f"{prefix}/api/v1/creation/media/{media.id}/file",
        "createdAt": media.created_at.isoformat(),
        "trashedAt": media.trashed_at.isoformat() if media.trashed_at else None,
    }


async def list_media(
    session: AsyncSession,
    user_id: str,
    *,
    asset_id: str | None = None,
    include_trashed: bool = False,
) -> list[CreationMedia]:
    query = select(CreationMedia).where(CreationMedia.user_id == user_id)
    if asset_id:
        query = query.where(CreationMedia.asset_id == asset_id)
    if not include_trashed:
        query = query.where(CreationMedia.trashed_at.is_(None))
    query = query.order_by(CreationMedia.created_at.desc())
    return list((await session.scalars(query)).all())


async def get_media(session: AsyncSession, user_id: str, media_id: str) -> CreationMedia:
    media = await session.get(CreationMedia, media_id)
    if media is None or media.user_id != user_id:
        raise ApiError(404, "ABM_NOT_FOUND", "Media not found.")
    return media


async def _existing_by_sha(session: AsyncSession, user_id: str, sha: str) -> CreationMedia | None:
    return await session.scalar(
        select(CreationMedia).where(
            CreationMedia.user_id == user_id,
            CreationMedia.sha256 == sha,
            CreationMedia.trashed_at.is_(None),
        )
    )


async def generate_media(
    session: AsyncSession,
    settings: Settings,
    storage: ObjectStorage,
    user: User,
    asset: CreationAsset,
    *,
    kind: str,
    platform: str,
    prompt: str,
    negative_prompt: str | None = None,
    n: int = 1,
    size: str | None = None,
    asset_version_id: str | None = None,
    reference_media_id: str | None = None,
    transport: Any | None = None,
) -> list[CreationMedia]:
    config = await load_config(session)
    limits = await quota_policy(settings).limits(session, user, config)
    target = await resolve_image_target(
        session, config, user, settings=settings, transport=transport
    )

    max_n = limits.image_max_n
    requested = max(1, min(int(n or 1), min(max_n, 4)))
    cover_size = PLATFORM_COVERS.get(platform) if kind == "cover" else None
    if size:
        resolved_size = size.strip()
    elif cover_size:
        resolved_size = provider_size_for(*cover_size)
    else:
        resolved_size = PLATFORM_SIZES.get(platform) or "1024x1024"

    reference: bytes | None = None
    reference_mime = "image/png"
    if reference_media_id:
        reference_row = await get_media(session, user.id, reference_media_id)
        reference = await storage.get(reference_row.storage_key)
        reference_mime = reference_row.mime

    clean_prompt = prompt.strip()[:MAX_PROMPT_CHARS]
    if not clean_prompt:
        raise ApiError(422, "ABM_VALIDATION", "Prompt must not be empty.")

    await assert_image_quota(session, user, limits, incoming_bytes=0)

    result = await target.provider.generate(
        prompt=clean_prompt,
        size=resolved_size,
        n=requested,
        reference=reference,
        reference_mime=reference_mime,
    )

    rows: list[CreationMedia] = []
    new_bytes = 0
    pending: list[tuple[Any, str, str]] = []
    for image in result.images:
        if image.mime not in MIME_SUFFIX:
            raise ApiError(
                502,
                "ABM_CREATION_IMAGE_FAILED",
                "The image provider returned an unsupported image format.",
                retryable=True,
                action="retry",
            )
        payload_bytes = image.data
        payload_mime = image.mime
        payload_width, payload_height = image.width, image.height
        if cover_size:
            payload_bytes = normalize_cover(payload_bytes, cover_size)
            payload_mime = "image/png"
            payload_width, payload_height = cover_size
        if len(payload_bytes) > settings.media_max_bytes:
            raise ApiError(
                413,
                "ABM_CREATION_IMAGE_TOO_LARGE",
                "The generated image exceeds the per-file size limit.",
                retryable=False,
                action="none",
            )
        sha = digest(payload_bytes)
        existing = await _existing_by_sha(session, user.id, sha)
        if existing is not None:
            rows.append(existing)
            continue
        pending.append((payload_bytes, payload_mime, payload_width, payload_height, sha))
        new_bytes += len(payload_bytes)

    if pending:
        await assert_image_quota(session, user, limits, incoming_bytes=new_bytes)

    for data, mime, width, height, sha in pending:
        suffix = MIME_SUFFIX[mime]
        key = media_key(user.id, sha, suffix)
        stored = await storage.put(key, data, content_type=mime)
        row = CreationMedia(
            user_id=user.id,
            project_id=asset.project_id,
            asset_id=asset.id,
            asset_version_id=asset_version_id or asset.current_version_id,
            kind=kind,
            platform=platform,
            role="generated",
            status="ready",
            prompt=clean_prompt,
            negative_prompt=(negative_prompt or "").strip()[:1000],
            provider_id=target.provider_id,
            model=result.model or target.model,
            width=width,
            height=height,
            mime=mime,
            storage_key=stored.key,
            bytes=stored.size,
            sha256=sha,
            meta={
                "size": resolved_size,
                "requested": requested,
                "coverSize": list(cover_size or []),
            },
        )
        session.add(row)
        rows.append(row)

    await session.flush()
    unique: list[CreationMedia] = []
    seen_ids: set[str] = set()
    for row in rows:
        if row.id in seen_ids:
            continue
        seen_ids.add(row.id)
        unique.append(row)
    return unique


async def update_media(
    session: AsyncSession,
    user_id: str,
    media_id: str,
    *,
    role: str | None = None,
    kind: str | None = None,
) -> CreationMedia:
    media = await get_media(session, user_id, media_id)
    if role:
        if role not in {"generated", "uploaded", "rendered", "cover", "inline"}:
            raise ApiError(422, "ABM_VALIDATION", "Unknown media role.")
        if role in {"cover", "inline"}:
            media.kind = role
            media.role = role
        else:
            media.role = role
    if kind:
        media.kind = kind
    return media


async def trash_media(
    session: AsyncSession, user_id: str, media_id: str, *, trash_days: int = 10
) -> CreationMedia:
    media = await get_media(session, user_id, media_id)
    moment = utcnow()
    media.status = "trashed"
    media.trashed_at = moment
    media.purge_after = moment + timedelta(days=max(1, trash_days))
    return media


async def restore_media(session: AsyncSession, user_id: str, media_id: str) -> CreationMedia:
    media = await get_media(session, user_id, media_id)
    media.status = "ready"
    media.trashed_at = None
    media.purge_after = None
    return media


async def cover_map(
    session: AsyncSession, user_id: str, asset_ids: list[str]
) -> dict[str, CreationMedia]:
    """Return the latest ready cover for each asset id."""

    if not asset_ids:
        return {}
    rows = await session.scalars(
        select(CreationMedia)
        .where(
            CreationMedia.user_id == user_id,
            CreationMedia.asset_id.in_(asset_ids),
            CreationMedia.role == "cover",
            CreationMedia.trashed_at.is_(None),
        )
        .order_by(CreationMedia.created_at.desc())
    )
    covers: dict[str, CreationMedia] = {}
    for row in rows:
        if row.asset_id and row.asset_id not in covers:
            covers[row.asset_id] = row
    return covers
