from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...auth.dependencies import RuntimeAuth, get_runtime_auth, get_video_auth
from ...errors import ApiError
from ...video import VideoError, VideoService, _serve_content_type

router = APIRouter(tags=["video"])
_STREAM_SLICE = 1024 * 1024


class JobResultRequest(BaseModel):
    step: str
    success: bool
    error: str | None = None
    chunkIndex: int | None = None


def _video_error(exc: VideoError) -> ApiError:
    return ApiError(
        exc.status_code,
        exc.code,
        exc.message,
        retryable=exc.retryable,
        action=exc.action,
    )


@router.get("/api/v1/video/config")
async def video_config(
    request: Request,
    auth: RuntimeAuth = Depends(get_video_auth),
) -> dict:
    service: VideoService = request.app.state.video_service
    return {"ok": True, **service.delivery_info(auth.api_key.id)}


@router.post("/api/v1/video/bridge-token")
async def issue_bridge_token(
    request: Request,
    auth: RuntimeAuth = Depends(get_runtime_auth),
) -> dict:
    service: VideoService = request.app.state.video_service
    if auth.api_key is None:
        raise ApiError(403, "ABM_FORBIDDEN", "API Key required.")
    token, expires_at = service.issue_bridge_token(auth.api_key.id)
    return {
        "token": token,
        "expiresAt": expires_at.isoformat(),
    }


@router.get("/api/v1/video/extension")
async def configured_extension(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "extensionId": settings.extension_id or "",
        "source": "configured",
    }


@router.get("/api/v1/video/jobs")
async def list_jobs(
    request: Request,
    pending: str | None = Query(default=None),
    auth: RuntimeAuth = Depends(get_video_auth),
) -> dict:
    service: VideoService = request.app.state.video_service
    return {
        "jobs": await service.list_jobs(
            auth.api_key.id,
            pending_only=pending == "1",
        )
    }


@router.get("/api/v1/video/jobs/{job_id}/chunks/{index}")
async def get_chunk(
    job_id: str,
    index: int,
    request: Request,
    auth: RuntimeAuth = Depends(get_video_auth),
) -> dict:
    service: VideoService = request.app.state.video_service
    try:
        return await service.get_chunk(job_id, index, api_key_id=auth.api_key.id)
    except VideoError as exc:
        raise _video_error(exc) from exc


@router.post("/api/v1/video/jobs/{job_id}/result", status_code=204)
async def report_result(
    job_id: str,
    payload: JobResultRequest,
    request: Request,
    auth: RuntimeAuth = Depends(get_video_auth),
) -> Response:
    service: VideoService = request.app.state.video_service
    try:
        await service.report_step(
            job_id,
            api_key_id=auth.api_key.id,
            step=payload.step,
            success=payload.success,
            error=payload.error,
        )
    except VideoError as exc:
        raise _video_error(exc) from exc
    return Response(status_code=204)


@router.head("/api/v1/downloads/{job_id}/{file_name}")
@router.get("/api/v1/downloads/{job_id}/{file_name}")
async def download_video(
    job_id: str,
    file_name: str,
    request: Request,
    token: str = Query(default=""),
):
    service: VideoService = request.app.state.video_service
    try:
        job = await service.download_job(job_id, token)
    except VideoError as exc:
        raise _video_error(exc) from exc
    headers = {
        "Content-Type": _serve_content_type(job.file_type),
        "Content-Length": str(job.file_size),
        "Cache-Control": "no-store",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(job.file_name)}",
    }
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)
    assert job.path is not None
    path = job.path

    async def stream():
        try:
            with open(path, "rb") as handle:
                while chunk := handle.read(_STREAM_SLICE):
                    yield chunk
            await service.mark_downloaded(job)
        except Exception as exc:
            job.error = str(exc)
            await service.report_step(
                job.id,
                api_key_id=job.api_key_id,
                step="download",
                success=False,
                error=str(exc),
            )
            raise

    return StreamingResponse(stream(), status_code=200, headers=headers)
