from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from ...auth.dependencies import AuthContext, get_current_auth, require_csrf

router = APIRouter(prefix="/api/v1/notices", tags=["notices"])


def _payload(notice) -> dict:
    return {
        "id": notice.id,
        "kind": notice.kind,
        "title": notice.title,
        "body": notice.body,
        "actionUrl": notice.action_url,
        "read": notice.read_at is not None,
        "createdAt": notice.created_at.isoformat(),
    }


@router.get("")
async def list_notices(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(get_current_auth),
) -> dict:
    notices = await request.app.state.notification_service.list(
        auth.user.id,
        limit=limit,
    )
    return {
        "items": [_payload(notice) for notice in notices],
        "unread": sum(1 for notice in notices if notice.read_at is None),
    }


@router.post("/{notice_id}/read", status_code=204)
async def mark_notice_read(
    notice_id: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
) -> Response:
    await request.app.state.notification_service.mark_read(auth.user.id, notice_id)
    return Response(status_code=204)


@router.post("/read-all", status_code=204)
async def mark_all_notices_read(
    request: Request,
    auth: AuthContext = Depends(require_csrf),
) -> Response:
    await request.app.state.notification_service.mark_all_read(auth.user.id)
    return Response(status_code=204)
