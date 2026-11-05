"""OpenAI-compatible chat client used by the creation pipeline.

Only ``POST /chat/completions`` is supported: the admin binds one provider per
plan and every provider must speak the same protocol. Provider errors are
mapped to ABM_* codes so the UI can explain what to fix instead of showing a
generic 500.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..errors import ApiError

_CHAT_SUFFIX = "/chat/completions"
_MAX_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 1.5


@dataclass(slots=True)
class Completion:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


def _content_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _usage(data: dict[str, Any]) -> tuple[int, int]:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    try:
        return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        return 0, 0


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:300]
        if isinstance(error, str):
            return error[:300]
        if payload.get("message"):
            return str(payload["message"])[:300]
    return response.text[:300]


async def chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 1600,
    temperature: float = 0.7,
    timeout: float = 90.0,
) -> Completion:
    url = base_url.rstrip("/") + _CHAT_SUFFIX
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response: httpx.Response | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            if attempt + 1 < _MAX_ATTEMPTS:
                await asyncio.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise ApiError(
                504,
                "ABM_CREATION_MODEL_TIMEOUT",
                "The model did not answer before the timeout.",
                retryable=True,
                action="retry",
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(
                502,
                "ABM_CREATION_MODEL_UNREACHABLE",
                "Could not reach the configured model endpoint.",
                retryable=True,
                action="retry",
            ) from exc

        status = response.status_code
        if status in {401, 403}:
            raise ApiError(
                502,
                "ABM_CREATION_MODEL_AUTH",
                "The model provider rejected the stored API key.",
                retryable=False,
                action="contact_admin",
            )
        if status == 404:
            raise ApiError(
                502,
                "ABM_CREATION_MODEL_NOT_FOUND",
                "The provider has no such model or chat endpoint.",
                retryable=False,
                action="contact_admin",
            )
        if status == 429 or status >= 500:
            if attempt + 1 < _MAX_ATTEMPTS:
                await asyncio.sleep(_RETRY_DELAY_SECONDS)
                continue
            code = "ABM_CREATION_MODEL_BUSY" if status == 429 else "ABM_CREATION_MODEL_UNAVAILABLE"
            raise ApiError(
                503,
                code,
                "The model provider is temporarily unavailable.",
                retryable=True,
                action="retry",
            )
        if status >= 400:
            raise ApiError(
                422,
                "ABM_CREATION_MODEL_REJECTED",
                f"The provider rejected the request: {_error_message(response)}",
                retryable=False,
                action="contact_admin",
            )
        break

    if response is None:  # pragma: no cover - defensive, the loop always sets it
        raise ApiError(502, "ABM_CREATION_MODEL_UNAVAILABLE", "No model response.", retryable=True)

    try:
        data = response.json()
    except ValueError as exc:
        raise ApiError(
            502,
            "ABM_CREATION_MODEL_BAD_RESPONSE",
            "The provider returned a non-JSON response.",
            retryable=True,
            action="retry",
        ) from exc

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ApiError(
            502,
            "ABM_CREATION_MODEL_BAD_RESPONSE",
            "The provider returned no choices.",
            retryable=True,
            action="retry",
        )
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    text = _content_text(message if isinstance(message, dict) else {})
    if not text.strip():
        raise ApiError(
            502,
            "ABM_CREATION_MODEL_BAD_RESPONSE",
            "The model returned an empty answer.",
            retryable=True,
            action="retry",
        )

    tokens_in, tokens_out = _usage(data)
    return Completion(
        text=text,
        model=str(data.get("model") or model),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        raw=data,
    )


__all__ = ["Completion", "chat_completion", "list_models"]


async def list_models(*, base_url: str, api_key: str, timeout: float = 10.0) -> list[str]:
    """Fetch model ids for the admin "test connection" flow."""

    url = base_url.rstrip("/") + "/models"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    if response.status_code in {401, 403}:
        raise ApiError(
            400,
            "ABM_CREATION_MODEL_AUTH",
            "The provider rejected this API key.",
            retryable=False,
        )
    if response.status_code >= 400:
        raise ApiError(
            400, "ABM_CREATION_MODEL_UNREACHABLE", "The provider did not answer /models."
        )
    payload = response.json()
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")]
