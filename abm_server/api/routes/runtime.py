from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...api_keys import list_user_api_keys
from ...auth.dependencies import AuthContext, RuntimeAuth, get_current_auth, get_runtime_auth
from ...database import get_session
from ...extension_gateway import ExtensionGateway
from ...tiers import tier_for

router = APIRouter(prefix="/api/v1", tags=["runtime"])


@router.get("/extension/status")
async def extension_status(
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    gateway: ExtensionGateway = request.app.state.extension_gateway
    keys = await list_user_api_keys(db, auth.user.id)
    connections = []
    for key in keys:
        key_connections = gateway.connections_info(key.id)
        info = key_connections[0] if key_connections else None
        connections.append(
            {
                "id": key.id,
                "name": key.name,
                "prefix": key.public_prefix,
                "status": "revoked" if key.revoked_at else "active",
                "online": bool(key_connections),
                "connectionCount": len(key_connections),
                "connections": key_connections,
                "extensionVersion": info.get("extensionVersion") if info else None,
                "connectedAt": info.get("connectedAt") if info else None,
                "lastSeen": info.get("lastSeen") if info else None,
            }
        )
    return {
        "connected": any(item["online"] for item in connections),
        "connections": connections,
    }


@router.get("/session/status")
async def session_status(
    request: Request,
    auth: RuntimeAuth = Depends(get_runtime_auth),
) -> dict:
    gateway: ExtensionGateway = request.app.state.extension_gateway
    api_key = auth.api_key
    return {
        "ok": True,
        "account": {
            "id": auth.user.id,
            "displayName": auth.user.display_name,
            "planCode": tier_for(auth.user, request.app.state.settings),
        },
        "apiKey": {
            "id": api_key.id,
            "prefix": api_key.public_prefix,
        },
        "connection": gateway.connection_info(api_key.id),
        "connections": gateway.connections_info(api_key.id),
        "pendingCalls": gateway.pending_count(api_key.id),
    }
