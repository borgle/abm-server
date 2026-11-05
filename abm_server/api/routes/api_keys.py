import contextlib

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...api_keys import create_api_key, list_user_api_keys, revoke_api_key
from ...auth.dependencies import AuthContext, get_current_auth, require_csrf
from ...database import get_session
from ...schemas import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyResponse

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


def _key_response(key) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=key.id,
        name=key.name,
        prefix=key.public_prefix,
        status="revoked" if key.revoked_at else "active",
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_keys(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> list[ApiKeyResponse]:
    return [_key_response(key) for key in await list_user_api_keys(db, auth.user.id)]


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
async def create_key(
    payload: ApiKeyCreateRequest,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> ApiKeyCreateResponse:
    async with request.app.state.key_locks.hold(auth.user.id):
        key, plaintext = await create_api_key(
            db,
            user=auth.user,
            name=payload.name,
            settings=request.app.state.settings,
        )
        await db.commit()
    await db.refresh(key)
    response = _key_response(key)
    return ApiKeyCreateResponse(**response.model_dump(), plaintext=plaintext)


@router.delete("/{key_id}", status_code=204)
async def delete_key(
    key_id: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Response:
    from ...extension_gateway import SessionError

    key = await revoke_api_key(db, user=auth.user, key_id=key_id)
    await db.commit()
    with contextlib.suppress(Exception):
        await request.app.state.notification_service.create(
            user_id=auth.user.id,
            kind="api_key",
            title="API Key revoked",
            body=(
                f"API Key {key.public_prefix} was revoked and its extension connection was closed."
            ),
            action_url="/console",
        )
    await request.app.state.extension_gateway.close_for_key(
        key.id,
        SessionError(
            "ABM_API_KEY_REVOKED",
            "API Key revoked.",
            1008,
            action="open_account_portal",
        ),
    )
    return Response(status_code=204)
