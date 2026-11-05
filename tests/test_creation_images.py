from __future__ import annotations

import base64
import json
import struct

import httpx
import pytest

from abm_server.creation.images import (
    OpenAIImagesProvider,
    build_openai_images_provider,
    image_dimensions,
)
from abm_server.errors import ApiError


def _png(width: int = 1024, height: int = 1536) -> bytes:
    header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
    return header + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"


def _provider(handler, *, model: str = "gpt-image-1") -> OpenAIImagesProvider:
    return OpenAIImagesProvider(
        base_url="https://images.example.com/v1",
        api_key="sk-test",
        model=model,
        retry_delay=0,
        transport=httpx.MockTransport(handler),
    )


async def test_generates_from_b64_json() -> None:
    payload = _png()
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "gpt-image-1",
                "data": [{"b64_json": base64.b64encode(payload).decode()}],
            },
        )

    result = await _provider(handler).generate(prompt="a cover", size="1024x1536", n=2)

    assert len(result.images) == 1
    assert result.images[0].data == payload
    assert result.images[0].mime == "image/png"
    assert (result.images[0].width, result.images[0].height) == (1024, 1536)
    assert calls[0]["prompt"] == "a cover"
    assert calls[0]["n"] == 2
    assert calls[0]["response_format"] == "b64_json"


async def test_downloads_url_response() -> None:
    image = _png(1080, 1440)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "https://cdn.test/a.png"}]})
        if request.url.host == "cdn.test":
            return httpx.Response(200, content=image, headers={"content-type": "image/png"})
        return httpx.Response(404)

    result = await _provider(handler).generate(prompt="cover", size="1024x1536")

    assert result.images[0].data == image
    assert (result.images[0].width, result.images[0].height) == (1080, 1440)


async def test_clamps_n_to_max() -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["n"])
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(_png()).decode()}]},
        )

    await _provider(handler).generate(prompt="cover", size="1024x1536", n=99)

    assert seen == [4]


async def test_auth_error_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(ApiError) as excinfo:
        await _provider(handler).generate(prompt="cover", size="1024x1536")

    assert excinfo.value.code == "ABM_CREATION_IMAGE_AUTH"
    assert excinfo.value.retryable is False
    assert calls == 1


async def test_rate_limit_is_retried_once() -> None:
    calls = 0
    image = base64.b64encode(_png()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(200, json={"data": [{"b64_json": image}]})

    result = await _provider(handler).generate(prompt="cover", size="1024x1536")

    assert calls == 2
    assert result.images


async def test_missing_config_reports_actionable_error() -> None:
    with pytest.raises(ApiError) as excinfo:
        build_openai_images_provider(base_url="", api_key="key", model="m")
    assert excinfo.value.code == "ABM_CREATION_IMAGE_NOT_CONFIGURED"


def test_dimension_sniffers() -> None:
    assert image_dimensions(_png(12, 34), "image/png") == (12, 34)
    assert image_dimensions(b"not an image", "application/octet-stream") == (0, 0)
