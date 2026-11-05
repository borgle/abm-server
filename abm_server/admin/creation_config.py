from __future__ import annotations

import base64
import binascii
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounts import get_setting, set_setting
from ..audit import record_audit
from ..config import Settings
from ..errors import ApiError
from ..models import User, utcnow

CREATION_CONFIG_SETTING = "creation_config"
CREATION_CONFIG_EVENT = "ABM_ADMIN_CREATION_UPDATED"

DEFAULT_LOCAL = {
    "providerId": None,
    "model": "",
    "fallbackModel": "",
    "imageProviderId": None,
    "imageModel": "",
    "imageMaxN": 4,
}


def default_config() -> dict:
    return {
        "enabled": True,
        "byokEnabled": True,
        "retentionDays": 30,
        "trashDays": 10,
        "providers": [],
        "local": dict(DEFAULT_LOCAL),
    }


def _merge_config(value: object) -> dict:
    config = default_config()
    if not isinstance(value, dict):
        return config
    for key in ("enabled", "byokEnabled"):
        if isinstance(value.get(key), bool):
            config[key] = value[key]
    for key in ("retentionDays", "trashDays"):
        if isinstance(value.get(key), int) and value[key] > 0:
            config[key] = value[key]
    providers = value.get("providers")
    if isinstance(providers, list):
        config["providers"] = [item for item in providers if isinstance(item, dict)]
    local = value.get("local")
    if isinstance(local, dict):
        config["local"].update(
            {key: local[key] for key in config["local"] if key in local}
        )
    return config


async def load_config(session: AsyncSession) -> dict:
    return _merge_config(await get_setting(session, CREATION_CONFIG_SETTING, None))


async def save_config(session: AsyncSession, config: dict, actor: User) -> dict:
    await set_setting(session, CREATION_CONFIG_SETTING, config, updated_by=actor.id)
    return config


def _secret_key(settings: Settings) -> bytes:
    raw = (settings.creation_secret_key or "").strip()
    if not raw:
        raise ApiError(
            409,
            "ABM_CREATION_SECRET_MISSING",
            "Creation secret key is not configured.",
        )
    try:
        key = base64.urlsafe_b64decode(raw)
    except (ValueError, binascii.Error) as exc:
        raise ApiError(
            500,
            "ABM_CREATION_SECRET_INVALID",
            "Creation secret key is invalid.",
        ) from exc
    if len(key) != 32:
        raise ApiError(
            500,
            "ABM_CREATION_SECRET_INVALID",
            "Creation secret key must decode to 32 bytes.",
        )
    return key


def encrypt_secret(settings: Settings, value: str) -> str:
    key = _secret_key(settings)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(settings: Settings, value: str) -> str:
    key = _secret_key(settings)
    try:
        payload = base64.urlsafe_b64decode(value)
        nonce, ciphertext = payload[:12], payload[12:]
        return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
    except (ValueError, binascii.Error) as exc:
        raise ApiError(
            500,
            "ABM_CREATION_SECRET_INVALID",
            "Stored creation secret cannot be decrypted.",
        ) from exc


def provider_public(provider: dict) -> dict:
    return {
        "id": provider.get("id"),
        "name": provider.get("name"),
        "baseUrl": provider.get("baseUrl"),
        "apiKeyLast4": provider.get("apiKeyLast4", ""),
        "hasApiKey": bool(provider.get("apiKeyCiphertext")),
        "status": provider.get("status", "unverified"),
        "lastVerifiedAt": provider.get("lastVerifiedAt"),
        "createdAt": provider.get("createdAt"),
    }


def public_config(config: dict) -> dict:
    return {
        "enabled": config["enabled"],
        "byokEnabled": config["byokEnabled"],
        "retentionDays": config["retentionDays"],
        "trashDays": config["trashDays"],
        "providers": [provider_public(item) for item in config["providers"]],
        "local": config["local"],
    }


def _find_provider(config: dict, provider_id: str) -> dict | None:
    return next((item for item in config["providers"] if item.get("id") == provider_id), None)


def _normalize_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parts = urlsplit(normalized)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ApiError(
            400,
            "ABM_VALIDATION_ERROR",
            "Provider base URL must be an absolute http(s) URL.",
        )
    return normalized


async def create_provider(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    *,
    name: str,
    base_url: str,
    api_key: str,
) -> dict:
    config = await load_config(session)
    provider = {
        "id": uuid4().hex,
        "name": name.strip(),
        "baseUrl": _normalize_base_url(base_url),
        "apiKeyCiphertext": encrypt_secret(settings, api_key),
        "apiKeyLast4": api_key[-4:],
        "status": "unverified",
        "lastVerifiedAt": None,
        "createdAt": utcnow().isoformat(),
    }
    config["providers"].append(provider)
    await save_config(session, config, actor)
    await _audit_config(session, actor, {"providerAdded": provider["id"]})
    return provider_public(provider)


async def update_provider(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    provider_id: str,
    *,
    name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict:
    config = await load_config(session)
    provider = _find_provider(config, provider_id)
    if provider is None:
        raise ApiError(404, "ABM_NOT_FOUND", "Provider not found.")
    changes: dict[str, dict[str, object]] = {}
    if name is not None and name.strip() != provider.get("name"):
        changes["name"] = {"before": provider.get("name"), "after": name.strip()}
        provider["name"] = name.strip()
    if base_url is not None:
        normalized = _normalize_base_url(base_url)
        if normalized != provider.get("baseUrl"):
            changes["baseUrl"] = {"before": provider.get("baseUrl"), "after": normalized}
            provider["baseUrl"] = normalized
    if api_key:
        provider["apiKeyCiphertext"] = encrypt_secret(settings, api_key)
        provider["apiKeyLast4"] = api_key[-4:]
        changes["apiKey"] = {"before": "***", "after": "***" + api_key[-4:]}
    provider["status"] = "unverified"
    await save_config(session, config, actor)
    await _audit_config(session, actor, changes)
    return provider_public(provider)


async def delete_provider(
    session: AsyncSession,
    actor: User,
    provider_id: str,
) -> None:
    config = await load_config(session)
    try:
        from abm_cloud.plans import ensure_provider_unused
    except ImportError:  # open-source build has no plans
        ensure_provider_unused = None
    if ensure_provider_unused is not None:
        await ensure_provider_unused(session, provider_id)
    before = len(config["providers"])
    config["providers"] = [item for item in config["providers"] if item.get("id") != provider_id]
    if len(config["providers"]) == before:
        raise ApiError(404, "ABM_NOT_FOUND", "Provider not found.")
    await save_config(session, config, actor)
    await _audit_config(session, actor, {"providerRemoved": provider_id})


async def test_provider(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    provider_id: str,
) -> dict:
    config = await load_config(session)
    provider = _find_provider(config, provider_id)
    if provider is None:
        raise ApiError(404, "ABM_NOT_FOUND", "Provider not found.")
    api_key = decrypt_secret(settings, provider["apiKeyCiphertext"])
    url = provider["baseUrl"].rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        ok = 200 <= response.status_code < 300
        message = None if ok else f"HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        ok = False
        message = str(exc)
    provider["status"] = "ok" if ok else "invalid"
    provider["lastVerifiedAt"] = utcnow().isoformat()
    await save_config(session, config, actor)
    await _audit_config(
        session,
        actor,
        {"providerTested": provider_id, "status": provider["status"]},
    )
    return {**provider_public(provider), "ok": ok, "message": message}


async def update_system(
    session: AsyncSession,
    actor: User,
    payload: dict,
) -> dict:
    config = await load_config(session)
    changes: dict[str, dict[str, object]] = {}
    for key in ("enabled", "byokEnabled", "retentionDays", "trashDays"):
        if key not in payload or payload[key] is None:
            continue
        if config.get(key) != payload[key]:
            changes[key] = {"before": config.get(key), "after": payload[key]}
            config[key] = payload[key]
    await save_config(session, config, actor)
    await _audit_config(session, actor, changes)
    return public_config(config)


async def _audit_config(
    session: AsyncSession,
    actor: User,
    changes: dict,
) -> None:
    record_audit(
        session,
        event_type=CREATION_CONFIG_EVENT,
        actor_user_id=actor.id,
        metadata={"changes": changes},
    )
