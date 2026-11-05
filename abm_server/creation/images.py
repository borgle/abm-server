"""Image generation providers.

Only the OpenAI Images protocol is implemented for now; other vendors are
plugged in by adding an adapter that satisfies :class:`ImageProvider`. The
module deliberately mirrors ``creation/llm.py``: one HTTP call, explicit error
codes, one retry for transient failures.
"""

from __future__ import annotations

import asyncio
import base64
import struct
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

from ..errors import ApiError

_GENERATE_SUFFIX = "/images/generations"
_EDIT_SUFFIX = "/images/edits"
_MAX_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 2.0
_MAX_IMAGES = 4


@dataclass(slots=True)
class GeneratedImage:
    data: bytes
    mime: str
    width: int = 0
    height: int = 0


@dataclass(slots=True)
class ImageResult:
    images: list[GeneratedImage]
    model: str
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ImageProvider(Protocol):
    kind: str

    async def generate(
        self,
        *,
        prompt: str,
        size: str,
        n: int = 1,
        seed: int | None = None,
        reference: bytes | None = None,
        reference_mime: str = "image/png",
    ) -> ImageResult: ...


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


def _error_for(status: int, message: str) -> ApiError:
    if status in (401, 403):
        return ApiError(
            502,
            "ABM_CREATION_IMAGE_AUTH",
            "The image provider rejected the API key.",
            retryable=False,
            action="contact_admin",
        )
    if status == 429:
        return ApiError(
            429,
            "ABM_CREATION_IMAGE_RATE_LIMITED",
            "The image provider is rate limiting requests. Try again shortly.",
            retryable=True,
            action="wait",
        )
    if status >= 500:
        return ApiError(
            502,
            "ABM_CREATION_IMAGE_FAILED",
            f"The image provider failed: {message}",
            retryable=True,
            action="retry",
        )
    return ApiError(
        502,
        "ABM_CREATION_IMAGE_FAILED",
        f"The image provider rejected the request: {message}",
        retryable=False,
        action="none",
    )


def _sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    return 0, 0


def _jpeg_size(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8"):
        return 0, 0
    index = 2
    length = len(data)
    while index + 9 < length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in {0xD8, 0xD9}:
            index += 2
            continue
        if marker == 0xDA:
            break
        segment = struct.unpack(">H", data[index + 2 : index + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC}:
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return int(width), int(height)
        index += 2 + segment
    return 0, 0


def _webp_size(data: bytes) -> tuple[int, int]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return 0, 0
    chunk = data[12:16]
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if chunk == b"VP8 ":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return 0, 0


def image_dimensions(data: bytes, mime: str) -> tuple[int, int]:
    if mime == "image/png":
        return _png_size(data)
    if mime == "image/jpeg":
        return _jpeg_size(data)
    if mime == "image/webp":
        return _webp_size(data)
    return 0, 0


class OpenAIImagesProvider:
    """Adapter for ``POST /images/generations`` (OpenAI-compatible gateways)."""

    kind = "openai-images"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120.0,
        retry_delay: float = _RETRY_DELAY_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.retry_delay = retry_delay
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def generate(
        self,
        *,
        prompt: str,
        size: str,
        n: int = 1,
        seed: int | None = None,
        reference: bytes | None = None,
        reference_mime: str = "image/png",
    ) -> ImageResult:
        count = max(1, min(int(n or 1), _MAX_IMAGES))
        last_error: ApiError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                if reference is not None:
                    return await self._edit(
                        prompt=prompt,
                        size=size,
                        n=count,
                        reference=reference,
                        reference_mime=reference_mime,
                    )
                return await self._generate(prompt=prompt, size=size, n=count, seed=seed)
            except ApiError as exc:
                last_error = exc
                if not exc.retryable or attempt == _MAX_ATTEMPTS - 1:
                    raise
                if self.retry_delay:
                    await asyncio.sleep(self.retry_delay)
            except httpx.TimeoutException as exc:
                last_error = ApiError(
                    504,
                    "ABM_CREATION_IMAGE_TIMEOUT",
                    "The image provider timed out.",
                    retryable=True,
                    action="retry",
                )
                if attempt == _MAX_ATTEMPTS - 1:
                    raise last_error from exc
                if self.retry_delay:
                    await asyncio.sleep(self.retry_delay)
        assert last_error is not None
        raise last_error

    async def _generate(
        self,
        *,
        prompt: str,
        size: str,
        n: int,
        seed: int | None,
    ) -> ImageResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": n,
            "size": size,
            "response_format": "b64_json",
        }
        if seed is not None:
            payload["seed"] = seed
        async with httpx.AsyncClient(
            timeout=self.timeout,
            transport=self.transport,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                self.base_url + _GENERATE_SUFFIX,
                json=payload,
                headers=self._headers(),
            )
        return await self._parse(response, model=self.model)

    async def _edit(
        self,
        *,
        prompt: str,
        size: str,
        n: int,
        reference: bytes,
        reference_mime: str,
    ) -> ImageResult:
        files = {"image": ("reference.png", reference, reference_mime)}
        data = {
            "model": self.model,
            "prompt": prompt,
            "n": str(n),
            "size": size,
        }
        async with httpx.AsyncClient(
            timeout=self.timeout,
            transport=self.transport,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                self.base_url + _EDIT_SUFFIX,
                data=data,
                files=files,
                headers=self._headers(),
            )
        return await self._parse(response, model=self.model)

    async def _parse(self, response: httpx.Response, *, model: str) -> ImageResult:
        if response.status_code >= 400:
            raise _error_for(response.status_code, _error_message(response))
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(
                502,
                "ABM_CREATION_IMAGE_FAILED",
                "The image provider returned a non-JSON response.",
                retryable=True,
                action="retry",
            ) from exc
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            raise ApiError(
                502,
                "ABM_CREATION_IMAGE_FAILED",
                "The image provider returned no images.",
                retryable=True,
                action="retry",
            )
        images: list[GeneratedImage] = []
        async with httpx.AsyncClient(
            timeout=self.timeout,
            transport=self.transport,
            follow_redirects=True,
        ) as client:
            for item in items:
                if not isinstance(item, dict):
                    continue
                data = await self._item_bytes(client, item)
                if not data:
                    continue
                mime = _sniff_mime(data)
                width, height = image_dimensions(data, mime)
                images.append(GeneratedImage(data=data, mime=mime, width=width, height=height))
        if not images:
            raise ApiError(
                502,
                "ABM_CREATION_IMAGE_FAILED",
                "The image provider returned images that could not be read.",
                retryable=True,
                action="retry",
            )
        return ImageResult(images=images, model=payload.get("model") or model, raw=payload)

    async def _item_bytes(self, client: httpx.AsyncClient, item: dict[str, Any]) -> bytes:
        encoded = item.get("b64_json")
        if isinstance(encoded, str) and encoded:
            try:
                return base64.b64decode(encoded, validate=True)
            except (ValueError, base64.binascii.Error):
                return b""
        url = item.get("url")
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            response = await client.get(url)
            if response.status_code < 400:
                return response.content
        return b""


def build_openai_images_provider(
    *,
    base_url: str,
    api_key: str,
    model: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OpenAIImagesProvider:
    if not base_url:
        raise ApiError(
            503,
            "ABM_CREATION_IMAGE_NOT_CONFIGURED",
            "No image provider base URL is configured.",
            retryable=False,
            action="contact_admin",
        )
    if not api_key:
        raise ApiError(
            503,
            "ABM_CREATION_IMAGE_NOT_CONFIGURED",
            "The image provider has no API key.",
            retryable=False,
            action="contact_admin",
        )
    if not model:
        raise ApiError(
            503,
            "ABM_CREATION_IMAGE_NOT_CONFIGURED",
            "No image model is bound to the current plan.",
            retryable=False,
            action="contact_admin",
        )
    return OpenAIImagesProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        transport=transport,
    )
