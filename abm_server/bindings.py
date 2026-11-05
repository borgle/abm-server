"""Model bindings for the single-user edition.

Hosted deployments resolve bindings from plans via the private cloud package;
the open-source build reads the local binding stored in the creation config.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .errors import ApiError
from .models import User


def _is_single(settings: Settings) -> bool:
    return (settings.edition or "hosted").strip().lower() == "single"


def _find_provider(config: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    return next(
        (item for item in config.get("providers", []) if item.get("id") == provider_id),
        None,
    )


async def resolve_chat(
    session: AsyncSession,
    config: dict[str, Any],
    settings: Settings,
    user: User,
) -> tuple[dict[str, Any], str, str]:
    if not _is_single(settings):
        from abm_cloud.bindings import resolve_chat as cloud_resolve

        return await cloud_resolve(session, config, user)

    local = config.get("local") or {}
    provider_id = local.get("providerId")
    model = str(local.get("model") or "").strip()
    if not provider_id or not model:
        raise ApiError(
            409,
            "ABM_CREATION_MODEL_NOT_CONFIGURED",
            "No local model is configured yet.",
            retryable=False,
            action="contact_admin",
        )
    provider = _find_provider(config, str(provider_id))
    if provider is None:
        raise ApiError(
            409,
            "ABM_CREATION_MODEL_NOT_CONFIGURED",
            "The configured provider no longer exists.",
            retryable=False,
            action="contact_admin",
        )
    return provider, model, str(local.get("fallbackModel") or "").strip()


async def resolve_image(
    session: AsyncSession,
    config: dict[str, Any],
    settings: Settings,
    user: User,
) -> tuple[str, str]:
    if not _is_single(settings):
        from abm_cloud.bindings import resolve_image as cloud_resolve

        return await cloud_resolve(session, config, user)

    local = config.get("local") or {}
    provider_id = str(local.get("imageProviderId") or "").strip()
    model = str(local.get("imageModel") or "").strip()
    if not provider_id or not model:
        raise ApiError(
            409,
            "ABM_CREATION_IMAGE_NOT_CONFIGURED",
            "No local image model is configured yet.",
            retryable=False,
            action="contact_admin",
        )
    if _find_provider(config, provider_id) is None:
        raise ApiError(
            409,
            "ABM_CREATION_IMAGE_NOT_CONFIGURED",
            "The configured image provider no longer exists.",
            retryable=False,
            action="contact_admin",
        )
    return provider_id, model
