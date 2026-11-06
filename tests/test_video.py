import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from abm_server.config import Settings
from abm_server.video.service import VideoError, VideoService


class FakeGateway:
    def __init__(self, result: dict | None = None) -> None:
        self.result = result or {"success": True}
        self.calls: list[dict] = []
        self.peer = type("Peer", (), {"extension_id": "fake-extension"})()

    def get_peer(self, api_key_id: str | None):
        return self.peer

    async def call_tool(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "content": [
                {"type": "text", "text": json.dumps(self.result)},
            ]
        }


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'video.db'}",
        "public_base_url": "https://abm.test",
        "video_temp_dir": str(tmp_path / "video"),
        "video_delivery": "auto",
    }
    values.update(overrides)
    return Settings(**values)


async def test_url_delivery_hands_original_url_to_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("URL delivery must not fetch the source on the server")

    monkeypatch.setattr(httpx, "AsyncClient", ExplodingClient)
    gateway = FakeGateway(
        {
            "success": True,
            "fileSize": 1234,
            "fileType": "video/mp4",
            "fileName": "clip.mp4",
        }
    )
    service = VideoService(gateway, make_settings(tmp_path))

    result = await service.stage(
        api_key_id="key",
        file_name="clip.mp4",
        file_type=None,
        base64_data=None,
        url="https://cdn.example.com/clip.mp4",
        delivery="url",
        timeout_ms=1000,
    )

    assert gateway.calls[0]["arguments"]["url"] == "https://cdn.example.com/clip.mp4"
    assert result["delivery"] == "url"
    assert result["fileSize"] == 1234
    assert result["fileType"] == "video/mp4"
    assert not (tmp_path / "video").exists() or not list((tmp_path / "video").glob("*.bin"))
    await service.shutdown()


async def test_auto_url_source_stays_direct(tmp_path: Path) -> None:
    gateway = FakeGateway({"success": True, "fileSize": 99, "fileType": "video/mp4"})
    service = VideoService(gateway, make_settings(tmp_path))

    result = await service.stage(
        api_key_id="key",
        file_name="clip.mp4",
        file_type=None,
        base64_data=None,
        url="https://cdn.example.com/auto.mp4",
        delivery="auto",
        timeout_ms=1000,
    )

    assert gateway.calls[0]["arguments"]["url"] == "https://cdn.example.com/auto.mp4"
    assert result["delivery"] == "url"
    assert result["fileSize"] == 99
    await service.shutdown()


async def test_permission_error_is_returned_as_actionable_error(tmp_path: Path) -> None:
    gateway = FakeGateway(
        {
            "success": False,
            "needPermission": True,
            "host": "cdn.example.com",
        }
    )
    service = VideoService(gateway, make_settings(tmp_path))

    with pytest.raises(VideoError) as error:
        await service.stage(
            api_key_id="key",
            file_name="clip.mp4",
            file_type=None,
            base64_data=None,
            url="https://cdn.example.com/clip.mp4",
            delivery="url",
            timeout_ms=1000,
        )

    assert error.value.code == "ABM_VIDEO_PERMISSION_REQUIRED"
    assert error.value.action == "open_extension"
    assert "cdn.example.com" in error.value.message
    await service.shutdown()


async def test_base64_url_delivery_stages_a_server_download_url(tmp_path: Path) -> None:
    payload = b"base64-video"
    gateway = FakeGateway({"success": True, "fileSize": len(payload)})
    service = VideoService(gateway, make_settings(tmp_path))

    result = await service.stage(
        api_key_id="key",
        file_name="clip.mp4",
        file_type="video/mp4",
        base64_data=base64.b64encode(payload).decode(),
        url=None,
        delivery="url",
        timeout_ms=1000,
    )

    download_url = gateway.calls[0]["arguments"]["url"]
    assert download_url.startswith("https://abm.test/api/v1/downloads/")
    assert "token=" in download_url
    assert result["delivery"] == "url"
    assert result["fileSize"] == len(payload)
    assert not list((tmp_path / "video").glob("*.bin"))
    await service.shutdown()


async def test_bridge_delivery_spools_to_a_temp_file_and_releases_it(tmp_path: Path) -> None:
    payload = b"bridge-video" * 1024
    gateway = FakeGateway()
    service = VideoService(gateway, make_settings(tmp_path))
    task = asyncio.create_task(
        service.stage(
            api_key_id="key",
            file_name="clip.mp4",
            file_type="video/mp4",
            base64_data=base64.b64encode(payload).decode(),
            url=None,
            delivery="bridge",
            timeout_ms=5000,
        )
    )

    job = None
    for _ in range(100):
        if service._jobs:
            job = next(iter(service._jobs.values()))
            break
        await asyncio.sleep(0.01)
    assert job is not None
    assert job.path is not None
    path = Path(job.path)
    assert path.exists()
    assert path.stat().st_size == len(payload)

    chunk = await service.get_chunk(job.id, 0, api_key_id="key")
    assert base64.b64decode(chunk["base64"]) == payload

    for step in ("start", "chunk", "complete"):
        await service.report_step(
            job.id,
            api_key_id="key",
            step=step,
            success=True,
            error=None,
        )
    result = await asyncio.wait_for(task, timeout=5)
    assert result["delivery"] == "bridge"
    assert result["fileSize"] == len(payload)
    assert not path.exists()
    await service.shutdown()


async def test_active_job_limit_is_enforced_per_api_key(tmp_path: Path) -> None:
    gateway = FakeGateway()
    service = VideoService(
        gateway,
        make_settings(tmp_path, video_max_jobs_per_key=1),
    )
    task = asyncio.create_task(
        service.stage(
            api_key_id="key",
            file_name="first.mp4",
            file_type="video/mp4",
            base64_data=base64.b64encode(b"first").decode(),
            url=None,
            delivery="bridge",
            timeout_ms=5000,
        )
    )
    job = None
    for _ in range(100):
        if service._jobs:
            job = next(iter(service._jobs.values()))
            break
        await asyncio.sleep(0.01)
    assert job is not None

    with pytest.raises(VideoError) as error:
        await service.stage(
            api_key_id="key",
            file_name="second.mp4",
            file_type="video/mp4",
            base64_data=base64.b64encode(b"second").decode(),
            url=None,
            delivery="bridge",
            timeout_ms=5000,
        )
    assert error.value.code == "ABM_VIDEO_BUSY"
    assert error.value.retryable is True

    for step in ("start", "complete"):
        await service.report_step(
            job.id,
            api_key_id="key",
            step=step,
            success=True,
            error=None,
        )
    await asyncio.wait_for(task, timeout=5)
    await service.shutdown()


def test_bridge_token_is_video_scoped(admin_client: TestClient) -> None:
    login = admin_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert login.status_code == 200
    csrf = admin_client.cookies.get("abm_csrf")
    assert csrf
    created = admin_client.post(
        "/api/v1/api-keys",
        json={"name": "bridge"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    api_key = created.json()["plaintext"]

    issued = admin_client.post(
        "/api/v1/video/bridge-token",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert issued.status_code == 200
    bridge_token = issued.json()["token"]
    assert bridge_token.startswith("abm_bridge_")

    config = admin_client.get(
        "/api/v1/video/config",
        headers={"Authorization": f"Bearer {bridge_token}"},
    )
    assert config.status_code == 200
    assert config.json()["ok"] is True

    runtime = admin_client.get(
        "/api/v1/session/status",
        headers={"Authorization": f"Bearer {bridge_token}"},
    )
    assert runtime.status_code == 401
    assert runtime.json()["error"]["code"] == "ABM_INVALID_API_KEY"
