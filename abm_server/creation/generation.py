"""Draft generation: sources + brief + platform -> a new asset version.

The pipeline mirrors docs/creation-module.md §9.4, minus streaming: the caller
waits for the full answer, the result is stored as one immutable version with
citations, source ids and token usage. Quotas are checked before the call so a
user does not pay for a request that would be rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..admin.creation_config import decrypt_secret, load_config
from ..audit import record_audit
from ..config import Settings
from ..errors import ApiError
from ..models import (
    CreationAsset,
    CreationAssetVersion,
    CreationProject,
    CreationSource,
    User,
    utcnow,
)
from ..quotas import Limits, quota_policy
from . import compose
from .bindings import resolve_chat
from .llm import chat_completion
from .service import create_asset, create_version, get_asset, get_project

PROMPT_MAX_CHARS = 48_000
PER_SOURCE_CHARS = 1_800
MAX_SOURCES = 24


@dataclass(slots=True)
class GenerationResult:
    asset: CreationAsset
    version: CreationAssetVersion
    draft: compose.ComposedDraft
    citations: list[dict[str, Any]]
    model: str
    model_source: str
    tokens_in: int
    tokens_out: int


def _day_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def resolve_model(
    session: AsyncSession,
    config: dict[str, Any],
    settings: Settings,
    user: User,
) -> tuple[dict[str, Any], str, str]:
    return await resolve_chat(session, config, settings, user)


async def _assert_quota(session: AsyncSession, user: User, limits: Limits) -> None:
    daily_limit = limits.generations_per_day
    if daily_limit:
        used = await session.scalar(
            select(func.count())
            .select_from(CreationAssetVersion)
            .where(
                CreationAssetVersion.user_id == user.id,
                CreationAssetVersion.model_source.is_not(None),
                CreationAssetVersion.created_at >= _day_start(),
            )
        )
        if int(used or 0) >= daily_limit:
            raise ApiError(
                429,
                "ABM_CREATION_GENERATION_LIMIT",
                "The daily generation limit for this plan is reached.",
                retryable=True,
                action="upgrade",
            )

    monthly_tokens = limits.tokens_per_month
    if monthly_tokens:
        used_tokens = await session.scalar(
            select(
                func.coalesce(
                    func.sum(CreationAssetVersion.tokens_in + CreationAssetVersion.tokens_out), 0
                )
            )
            .select_from(CreationAssetVersion)
            .where(
                CreationAssetVersion.user_id == user.id,
                CreationAssetVersion.created_at >= _month_start(),
            )
        )
        if int(used_tokens or 0) >= monthly_tokens:
            raise ApiError(
                429,
                "ABM_CREATION_TOKEN_QUOTA",
                "The monthly token quota for this plan is exhausted.",
                retryable=True,
                action="upgrade",
            )


async def _load_sources(
    session: AsyncSession, user_id: str, source_ids: list[str]
) -> list[CreationSource]:
    unique: list[str] = []
    for item in source_ids:
        if item and item not in unique:
            unique.append(item)
    if not unique:
        raise ApiError(
            422,
            "ABM_VALIDATION_ERROR",
            "Select at least one source before generating.",
        )
    if len(unique) > MAX_SOURCES:
        unique = unique[:MAX_SOURCES]
    rows = list(
        await session.scalars(
            select(CreationSource).where(
                CreationSource.user_id == user_id,
                CreationSource.id.in_(unique),
                CreationSource.trashed_at.is_(None),
            )
        )
    )
    by_id = {row.id: row for row in rows}
    ordered = [by_id[item] for item in unique if item in by_id]
    if not ordered:
        raise ApiError(404, "ABM_NOT_FOUND", "None of the selected sources exist.")
    return ordered


def _material(row: CreationSource) -> compose.SourceMaterial:
    return compose.SourceMaterial(
        id=row.id,
        title=row.title or row.canonical_url,
        url=row.url or row.canonical_url,
        author=row.author,
        published_at=row.published_at,
        fetched_at=row.fetched_at.isoformat() if row.fetched_at else None,
        excerpt=row.excerpt or "",
        text=row.content_text or "",
    )


async def _call_model(
    *,
    settings: Settings,
    provider: dict[str, Any],
    model: str,
    fallback_model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> tuple[str, str, int, int]:
    api_key = decrypt_secret(settings, provider["apiKeyCiphertext"])
    attempts = [model]
    if fallback_model and fallback_model != model:
        attempts.append(fallback_model)

    last_error: ApiError | None = None
    for attempt in attempts:
        try:
            completion = await chat_completion(
                base_url=provider["baseUrl"],
                api_key=api_key,
                model=attempt,
                messages=messages,
                max_tokens=max_tokens,
            )
        except ApiError as exc:
            last_error = exc
            if exc.code in {"ABM_CREATION_MODEL_AUTH", "ABM_CREATION_MODEL_NOT_FOUND"}:
                raise
            continue
        return (
            completion.text,
            completion.model,
            completion.tokens_in,
            completion.tokens_out,
        )
    assert last_error is not None
    raise last_error


async def generate_draft(
    session: AsyncSession,
    settings: Settings,
    user: User,
    *,
    platform: str,
    brief: dict[str, Any] | None = None,
    source_ids: list[str],
    asset_id: str | None = None,
    project_id: str | None = None,
    title: str | None = None,
) -> GenerationResult:
    platform = platform if platform in compose.PLATFORM_STYLES else compose.DEFAULT_PLATFORM
    brief = brief or {}

    config = await load_config(session)
    if not config.get("enabled", True):
        raise ApiError(
            409,
            "ABM_CREATION_DISABLED",
            "The creation studio is disabled by the administrator.",
            retryable=False,
            action="contact_admin",
        )

    provider, model, fallback_model = await resolve_model(session, config, settings, user)
    limits = await quota_policy(settings).limits(session, user, config)
    await _assert_quota(session, user, limits)

    if asset_id:
        asset = await get_asset(session, user.id, asset_id)
        project_id = asset.project_id
    elif project_id:
        project: CreationProject = await get_project(session, user.id, project_id)
        project_id = project.id
    else:
        asset = None

    sources = await _load_sources(session, user.id, source_ids)
    materials = [_material(row) for row in sources]
    messages = compose.build_messages(
        platform=platform,
        brief=brief,
        sources=materials,
        per_source_chars=PER_SOURCE_CHARS,
    )
    prompt_chars = sum(len(message["content"]) for message in messages)
    if prompt_chars > PROMPT_MAX_CHARS:
        raise ApiError(
            422,
            "ABM_CREATION_CONTEXT_TOO_LARGE",
            "The selected sources are too large. Deselect a few and retry.",
            retryable=False,
        )

    style = compose.platform_style(platform)
    max_tokens = min(4096, max(600, int(style["target_chars"] * 2)))
    default_title = title or (sources[0].title if sources else "未命名草稿")

    text, used_model, tokens_in, tokens_out = await _call_model(
        settings=settings,
        provider=provider,
        model=model,
        fallback_model=fallback_model,
        messages=messages,
        max_tokens=max_tokens,
    )
    draft = compose.parse_draft(text, platform=platform, fallback_title=default_title)

    # Structured output that we could not read (bad JSON, wrong shape): ask the
    # model once to re-emit valid JSON instead of saving raw JSON as the article.
    if not draft.body.strip():
        repair_messages = [
            *messages,
            {"role": "assistant", "content": text[:6000]},
            {"role": "user", "content": compose.REPAIR_PROMPT},
        ]
        repair_text, used_model, repair_in, repair_out = await _call_model(
            settings=settings,
            provider=provider,
            model=model,
            fallback_model=fallback_model,
            messages=repair_messages,
            max_tokens=max_tokens,
        )
        tokens_in += repair_in
        tokens_out += repair_out
        draft = compose.parse_draft(
            repair_text,
            platform=platform,
            fallback_title=default_title,
        )

    if not draft.body.strip():
        raise ApiError(
            502,
            "ABM_CREATION_BAD_DRAFT",
            "The model did not return a parsable draft. Retry or switch model.",
            retryable=True,
            action="retry",
        )

    citations = [material.citation() for material in materials]

    if asset is None:
        asset = await create_asset(
            session,
            user,
            title=(title or draft.title or "未命名草稿")[:200],
            kind=str(style.get("kind") or "article"),
            project_id=project_id,
            platform=platform,
            content_md=draft.body,
            outline=draft.outline,
            brief=brief,
            citations=citations,
            source_ids=[material.id for material in materials],
            created_by="system",
            model_source="builtin",
            model=used_model,
            prompt_version=compose.PROMPT_VERSION,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        version = await session.get(CreationAssetVersion, asset.current_version_id)
        assert version is not None
    else:
        version = await create_version(
            session,
            user.id,
            asset.id,
            content_md=draft.body,
            title=draft.title if draft.title and draft.title != asset.title else None,
            outline=draft.outline,
            brief=brief,
            citations=citations,
            source_ids=[material.id for material in materials],
            created_by="system",
            model_source="builtin",
            model=used_model,
            prompt_version=compose.PROMPT_VERSION,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        asset.master_platform = platform
        asset.updated_at = utcnow()
    if draft.tags:
        asset.tags = draft.tags[:10]
        asset.updated_at = utcnow()
    record_audit(
        session,
        event_type="ABM_CREATION_ASSET_GENERATED",
        actor_user_id=user.id,
        subject_user_id=user.id,
        metadata={
            "assetId": asset.id,
            "versionId": version.id,
            "platform": platform,
            "model": used_model,
            "providerId": provider.get("id"),
            "sourceCount": len(materials),
            "tokensIn": tokens_in,
            "tokensOut": tokens_out,
        },
    )
    return GenerationResult(
        asset=asset,
        version=version,
        draft=draft,
        citations=citations,
        model=used_model,
        model_source="builtin",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )


__all__ = ["GenerationResult", "generate_draft", "resolve_model"]
