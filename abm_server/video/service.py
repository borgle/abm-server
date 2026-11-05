from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from ..config import Settings
from ..extension_gateway import ExtensionGateway, GatewayCallError

logger = logging.getLogger(__name__)

DELIVERY_MODES = ("bridge", "url", "auto")
DOWNLOAD_TOOL = "browser_download_video_from_url"
_VIDEO_TYPES = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
    "video/webm": "webm",
    "video/x-matroska": "mkv",
}
# 4MB 的 base64 切片（必须是 4 的倍数，避免切断编码单元）
_BASE64_BLOCK = 4 * 1024 * 1024
_ACTIVE_STATUSES = {"pending", "delivering"}


def _new_completion_future() -> asyncio.Future[str]:
    return asyncio.get_running_loop().create_future()


class VideoError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        action: str = "none",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.action = action


@dataclass(slots=True)
class VideoJob:
    id: str
    api_key_id: str
    file_name: str
    file_type: str
    file_size: int
    total_chunks: int
    delivery: str
    token: str
    created_at: datetime
    path: str | None = None
    status: str = "pending"
    download_url: str | None = None
    error: str | None = None
    warning: str | None = None
    delivered_at: datetime | None = None
    completion: asyncio.Future[str] = field(default_factory=_new_completion_future)


@dataclass(slots=True)
class BridgeToken:
    api_key_id: str
    expires_at: datetime


def _normalize_delivery(value: str | None, default: str) -> str:
    selected = (value or default or "auto").strip().lower()
    if selected not in DELIVERY_MODES:
        raise VideoError(
            "ABM_VALIDATION_ERROR",
            f"delivery must be one of {', '.join(DELIVERY_MODES)}.",
        )
    return selected


def _strip_data_url(value: str) -> str:
    if value.startswith("data:") and "," in value:
        return value.split(",", 1)[1]
    return value


def _download_file_name(file_name: str, file_type: str) -> str:
    base = Path(file_name).name
    if "." in base:
        return base
    extension = _VIDEO_TYPES.get(file_type.lower(), "mp4")
    return f"{base}.{extension}"


def _serve_content_type(file_type: str) -> str:
    value = (file_type or "").lower()
    if value.startswith("video/") or value == "application/octet-stream":
        return value
    return "application/octet-stream"


class VideoService:
    def __init__(self, gateway: ExtensionGateway, settings: Settings):
        self.gateway = gateway
        self.settings = settings
        self._jobs: dict[str, VideoJob] = {}
        self._bridge_tokens: dict[str, BridgeToken] = {}
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task | None = None

    async def start(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reaper_loop())

    async def stop(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            await asyncio.gather(self._reaper, return_exceptions=True)
            self._reaper = None

    async def _reaper_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(60)
                now = datetime.now(UTC)
                expired: list[VideoJob] = []
                async with self._lock:
                    for job in self._jobs.values():
                        age_ms = (now - job.created_at).total_seconds() * 1000
                        if age_ms > self.settings.video_job_ttl_ms:
                            expired.append(job)
                    for job in expired:
                        self._jobs.pop(job.id, None)
                for job in expired:
                    self._settle(job, "failed", "Video job expired.")
                    self._release(job)
        except asyncio.CancelledError:
            raise

    def _settle(self, job: VideoJob, status: str, error: str | None = None) -> None:
        if job.status == "delivered" or job.status == "failed":
            return
        job.status = status
        job.error = error
        if status == "delivered":
            job.delivered_at = datetime.now(UTC)
        if not job.completion.done():
            job.completion.set_result(status)

    def _temp_dir(self) -> Path:
        configured = self.settings.video_temp_dir.strip()
        base = (
            Path(configured).expanduser()
            if configured
            else Path(tempfile.gettempdir()) / "abm-video"
        )
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _temp_path(self, job_id: str) -> str:
        return str(self._temp_dir() / f"{job_id}.bin")

    def _cleanup_path(self, path: str | None) -> None:
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove temporary video file %s", path)

    def _release(self, job: VideoJob) -> None:
        path = job.path
        job.path = None
        job.download_url = None
        self._cleanup_path(path)

    def _prune_bridge_tokens(self) -> None:
        now = datetime.now(UTC)
        for digest, record in list(self._bridge_tokens.items()):
            if record.expires_at <= now:
                self._bridge_tokens.pop(digest, None)

    def issue_bridge_token(self, api_key_id: str) -> tuple[str, datetime]:
        self._prune_bridge_tokens()
        token = f"abm_bridge_{secrets.token_urlsafe(32)}"
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(
            seconds=self.settings.video_bridge_token_ttl_seconds
        )
        self._bridge_tokens[digest] = BridgeToken(
            api_key_id=api_key_id,
            expires_at=expires_at,
        )
        return token, expires_at

    def resolve_bridge_token(self, token: str) -> str | None:
        if not token.startswith("abm_bridge_"):
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        record = self._bridge_tokens.get(digest)
        if record is None:
            return None
        if record.expires_at <= datetime.now(UTC):
            self._bridge_tokens.pop(digest, None)
            return None
        return record.api_key_id

    def _base_url(self) -> str:
        return (
            self.settings.public_base_url.strip().rstrip("/")
            or f"http://127.0.0.1:{self.settings.port}"
        )

    def _assert_capacity_locked(self, api_key_id: str) -> None:
        active = [job for job in self._jobs.values() if job.status in _ACTIVE_STATUSES]
        per_key = sum(1 for job in active if job.api_key_id == api_key_id)
        if per_key >= self.settings.video_max_jobs_per_key:
            raise VideoError(
                "ABM_VIDEO_BUSY",
                "Too many active video jobs for this API key. Wait for one to finish.",
                retryable=True,
                action="wait",
            )
        if len(active) >= self.settings.video_max_jobs_total:
            raise VideoError(
                "ABM_VIDEO_BUSY",
                "The server has reached its active video job limit. Try again later.",
                retryable=True,
                action="wait",
            )

    async def _write_base64_to_file(self, job_id: str, data: str) -> tuple[str, int]:
        cleaned = _strip_data_url(data).strip()
        if not cleaned:
            raise VideoError("ABM_VIDEO_EMPTY", "Video content is empty.")
        path = self._temp_path(job_id)
        size = 0
        try:
            with open(path, "wb") as handle:
                for offset in range(0, len(cleaned), _BASE64_BLOCK):
                    piece = cleaned[offset : offset + _BASE64_BLOCK]
                    try:
                        raw = base64.b64decode(piece, validate=False)
                    except Exception as exc:
                        raise VideoError(
                            "ABM_VALIDATION_ERROR",
                            "Invalid base64 video data.",
                        ) from exc
                    size += len(raw)
                    if size > self.settings.max_video_bytes:
                        raise VideoError(
                            "ABM_VIDEO_TOO_LARGE",
                            "Video exceeds the size limit.",
                            status_code=413,
                        )
                    handle.write(raw)
        except Exception:
            self._cleanup_path(path)
            raise
        if size == 0:
            self._cleanup_path(path)
            raise VideoError("ABM_VIDEO_EMPTY", "Video content is empty.")
        return path, size

    async def _stream_url_to_file(
        self,
        job_id: str,
        url: str,
        file_type: str | None,
    ) -> tuple[str, int, str]:
        path = self._temp_path(job_id)
        size = 0
        try:
            async with (
                httpx.AsyncClient(timeout=300, follow_redirects=True) as client,
                client.stream("GET", url) as response,
            ):
                response.raise_for_status()
                length = response.headers.get("content-length")
                if length and length.isdigit() and int(length) > self.settings.max_video_bytes:
                    raise VideoError(
                        "ABM_VIDEO_TOO_LARGE",
                        "Video exceeds the size limit.",
                        status_code=413,
                    )
                with open(path, "wb") as handle:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.settings.max_video_bytes:
                            raise VideoError(
                                "ABM_VIDEO_TOO_LARGE",
                                "Video exceeds the size limit.",
                                status_code=413,
                            )
                        handle.write(chunk)
                resolved_type = (
                    file_type or response.headers.get("content-type", "video/mp4").split(";")[0]
                )
        except VideoError:
            self._cleanup_path(path)
            raise
        except Exception as exc:
            self._cleanup_path(path)
            raise VideoError(
                "ABM_VIDEO_SOURCE_FETCH_FAILED",
                f"Failed to download the video source: {exc}",
                retryable=True,
                action="wait",
            ) from exc
        if size == 0:
            self._cleanup_path(path)
            raise VideoError("ABM_VIDEO_EMPTY", "Video content is empty.")
        return path, size, resolved_type

    def _server_download_url(self, job_id: str, file_name: str, file_type: str, token: str) -> str:
        download_name = quote(_download_file_name(file_name, file_type), safe="")
        return f"{self._base_url()}/api/v1/downloads/{job_id}/{download_name}?token={token}"

    async def stage(
        self,
        *,
        api_key_id: str,
        file_name: str,
        file_type: str | None,
        base64_data: str | None,
        url: str | None,
        delivery: str | None,
        timeout_ms: int | None,
    ) -> dict[str, Any]:
        if not file_name:
            raise VideoError("ABM_VALIDATION_ERROR", "fileName is required.")
        if not base64_data and not url:
            raise VideoError("ABM_VIDEO_EMPTY", "Provide either base64 data or a URL.")

        requested = _normalize_delivery(delivery, self.settings.video_delivery)
        connected = self.gateway.get_peer(api_key_id) is not None
        if requested == "auto":
            # URL 源优先让扩展直连；base64 仍需要服务端托管或 bridge。
            mode = "url" if (url and not base64_data) or connected else "bridge"
        else:
            mode = requested

        # 先做一次容量预检，避免先下载大文件再发现超限。
        async with self._lock:
            self._assert_capacity_locked(api_key_id)

        job_id = f"video_{uuid4().hex}"
        token = secrets.token_urlsafe(24)
        path: str | None = None
        size = 0
        total_chunks = 0
        resolved_type = file_type or "video/mp4"
        download_url: str | None = None
        warning: str | None = None
        relayed_bytes = 0
        job: VideoJob | None = None

        try:
            if base64_data:
                path, size = await self._write_base64_to_file(job_id, base64_data)
                relayed_bytes = size
                total_chunks = max(
                    1,
                    (size + self.settings.video_chunk_bytes - 1) // self.settings.video_chunk_bytes,
                )
                if mode == "url":
                    download_url = self._server_download_url(
                        job_id, file_name, resolved_type, token
                    )
                if size >= 100 * 1024 * 1024:
                    warning = (
                        "Large base64 payloads are relayed through the server. "
                        "For files already on the user's machine, prefer "
                        "browser_set_files_native so bytes stay local."
                    )
            elif url and mode == "url":
                # 直连：服务端只把原始 URL 交给扩展，不下载、不落盘。
                total_chunks = 1
                download_url = url
            elif url:
                path, size, resolved_type = await self._stream_url_to_file(job_id, url, file_type)
                relayed_bytes = size
                total_chunks = max(
                    1,
                    (size + self.settings.video_chunk_bytes - 1) // self.settings.video_chunk_bytes,
                )
                if size >= 100 * 1024 * 1024:
                    warning = (
                        "Bridge delivery relays video bytes through the server. "
                        "Prefer URL delivery or browser_set_files_native for large files."
                    )
            else:
                raise VideoError("ABM_VIDEO_EMPTY", "Provide either base64 data or a URL.")

            job = VideoJob(
                id=job_id,
                api_key_id=api_key_id,
                file_name=file_name,
                file_type=resolved_type,
                file_size=size,
                total_chunks=total_chunks,
                path=path,
                delivery=mode,
                token=token,
                created_at=datetime.now(UTC),
                download_url=download_url,
                warning=warning,
            )
            async with self._lock:
                self._assert_capacity_locked(api_key_id)
                self._jobs[job.id] = job

            if mode == "url":
                try:
                    await self._deliver_url(job, timeout_ms)
                    self._settle(job, "delivered")
                except GatewayCallError as exc:
                    self._settle(job, "failed", exc.message)
                    self._release(job)
                    raise VideoError(
                        exc.code,
                        exc.message,
                        retryable=exc.retryable,
                        action=exc.action,
                    ) from exc

            if job.status == "pending":
                wait_ms = max(5000, timeout_ms or self.settings.tool_timeout_ms)
                try:
                    await asyncio.wait_for(job.completion, timeout=wait_ms / 1000)
                except TimeoutError:
                    self._settle(job, "failed", "Video delivery timed out.")

            if job.status != "delivered":
                self._release(job)
                raise VideoError(
                    "ABM_VIDEO_DELIVERY_FAILED",
                    job.error or "Video delivery failed.",
                    retryable=True,
                    action="wait",
                )

            result = {
                "sessionId": job.id,
                "fileName": job.file_name,
                "fileType": job.file_type,
                "fileSize": job.file_size,
                "delivery": job.delivery,
                "status": job.status,
                "relayedBytes": relayed_bytes,
            }
            if job.warning:
                result["warning"] = job.warning
            self._release(job)
            return result
        except BaseException:
            if job is not None:
                self._settle(job, "failed", "Video delivery was interrupted.")
                self._release(job)
            self._cleanup_path(path)
            raise

    async def _deliver_url(self, job: VideoJob, timeout_ms: int | None) -> None:
        timeout = max(10_000, timeout_ms or self.settings.tool_timeout_ms)
        result = await self.gateway.call_tool(
            api_key_id=job.api_key_id,
            name=DOWNLOAD_TOOL,
            arguments={"url": job.download_url, "timeout": timeout},
            timeout_ms=timeout + 15_000,
        )
        text = "\n".join(
            str(item.get("text", ""))
            for item in result.get("content", [])
            if isinstance(item, dict)
        )
        try:
            info = json.loads(text) if text else {}
        except json.JSONDecodeError:
            info = {}
        if info.get("needPermission"):
            raise GatewayCallError(
                "ABM_VIDEO_PERMISSION_REQUIRED",
                f"Extension is not authorized to access {info.get('host', 'the video URL')}.",
                retryable=True,
                action="open_extension",
            )
        if info.get("success") is not True:
            raise GatewayCallError(
                "ABM_VIDEO_DELIVERY_FAILED",
                text or "The extension failed to download the video.",
                retryable=True,
                action="wait",
            )
        actual_size = info.get("fileSize")
        if isinstance(actual_size, int) and actual_size >= 0:
            if job.path is not None and actual_size != job.file_size:
                job.warning = (
                    f"Extension received {actual_size} bytes, but the server staged "
                    f"{job.file_size} bytes."
                )
            job.file_size = actual_size
        actual_type = info.get("fileType")
        if isinstance(actual_type, str) and actual_type:
            job.file_type = actual_type
        actual_name = info.get("fileName")
        if isinstance(actual_name, str) and actual_name:
            job.file_name = actual_name

    def delivery_info(self, api_key_id: str | None = None) -> dict[str, Any]:
        peer = self.gateway.get_peer(api_key_id) if api_key_id else None
        return {
            "delivery": self.settings.video_delivery,
            "modes": list(DELIVERY_MODES),
            "chunkLimitBytes": self.settings.video_chunk_bytes,
            "maxVideoBytes": self.settings.max_video_bytes,
            "maxJobsPerKey": self.settings.video_max_jobs_per_key,
            "maxJobsTotal": self.settings.video_max_jobs_total,
            "publicBaseUrl": self.settings.public_base_url or None,
            "extensionId": peer.extension_id if peer else None,
        }

    async def list_jobs(
        self,
        api_key_id: str,
        *,
        pending_only: bool = False,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            jobs = list(self._jobs.values())
        output = []
        for job in jobs:
            if job.api_key_id != api_key_id:
                continue
            if pending_only and (job.status not in _ACTIVE_STATUSES or job.delivery == "url"):
                continue
            output.append(
                {
                    "sessionId": job.id,
                    "fileName": job.file_name,
                    "fileType": job.file_type,
                    "fileSize": job.file_size,
                    "totalChunks": job.total_chunks,
                    "status": job.status,
                    "delivery": job.delivery,
                }
            )
        return output

    async def get_chunk(
        self,
        job_id: str,
        index: int,
        *,
        api_key_id: str,
    ) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None or job.api_key_id != api_key_id:
            raise VideoError("ABM_VIDEO_JOB_NOT_FOUND", "Video job not found.", status_code=404)
        if index < 0 or index >= job.total_chunks:
            raise VideoError("ABM_VIDEO_JOB_NOT_FOUND", "Video chunk not found.", status_code=404)
        if job.path is None:
            raise VideoError(
                "ABM_VIDEO_EXPIRED", "Video content has been released.", status_code=410
            )
        try:
            with open(job.path, "rb") as handle:
                handle.seek(index * self.settings.video_chunk_bytes)
                data = handle.read(self.settings.video_chunk_bytes)
        except OSError as exc:
            raise VideoError(
                "ABM_VIDEO_EXPIRED", "Video content has been released.", status_code=410
            ) from exc
        return {
            "index": index,
            "totalChunks": job.total_chunks,
            "base64": base64.b64encode(data).decode("ascii"),
        }

    async def report_step(
        self,
        job_id: str,
        *,
        api_key_id: str,
        step: str,
        success: bool,
        error: str | None,
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.api_key_id != api_key_id:
            raise VideoError("ABM_VIDEO_JOB_NOT_FOUND", "Video job not found.", status_code=404)
        if not success:
            self._settle(job, "failed", error or f"Bridge step failed: {step}")
            return
        if step == "start" and job.status == "pending":
            job.status = "delivering"
        elif step == "complete":
            self._settle(job, "delivered")

    async def download_job(self, job_id: str, token: str) -> VideoJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise VideoError("ABM_VIDEO_JOB_NOT_FOUND", "Video not found.", status_code=404)
        if not token or not secrets.compare_digest(token, job.token):
            raise VideoError("ABM_VIDEO_TOKEN_INVALID", "Invalid download token.", status_code=403)
        if job.path is None or job.status in {"delivered", "failed"}:
            raise VideoError(
                "ABM_VIDEO_EXPIRED", "Video has been released or expired.", status_code=410
            )
        if job.status == "pending":
            job.status = "delivering"
        return job

    async def mark_downloaded(self, job: VideoJob) -> None:
        self._settle(job, "delivered")
        self._release(job)

    async def shutdown(self) -> None:
        for job in list(self._jobs.values()):
            self._settle(job, "failed", "Server is shutting down.")
            self._release(job)
        self._jobs.clear()
        self._bridge_tokens.clear()
        await self.stop()
