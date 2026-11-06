from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...api_keys import resolve_api_key
from ...errors import ApiError
from ...extension_gateway import (
    PROTOCOL_VERSION,
    WS_SUBPROTOCOL,
    ExtensionGateway,
    GatewayCallError,
    GatewayPeer,
    SessionError,
    envelope,
    error_envelope,
    validate_envelope,
)
from ...tiers import tier_for

logger = logging.getLogger(__name__)
router = APIRouter(tags=["extension"])


def _malformed(message: str) -> SessionError:
    return SessionError(
        "ABM_PROTOCOL_ERROR",
        message,
        1008,
        action="upgrade_extension",
    )


def _parse_message(raw: str) -> dict:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _malformed("Message is not valid JSON.") from exc
    validate_envelope(message)
    return message


async def _authenticate_hello(websocket: WebSocket, message: dict):
    if message.get("type") != "session.hello":
        raise _malformed("The first message must be session.hello.")
    payload = message["payload"]
    api_key = payload.get("apiKey")
    extension_id = payload.get("extensionId")
    extension_version = payload.get("extensionVersion")
    if (
        not isinstance(api_key, str)
        or not api_key
        or not isinstance(extension_id, str)
        or not extension_id
        or not isinstance(extension_version, str)
        or not extension_version
    ):
        raise _malformed("session.hello is missing required fields.")
    database = websocket.app.state.database
    try:
        async with database.sessions() as db:
            api_key_row, user = await resolve_api_key(db, api_key)
            await db.commit()
    except ApiError as exc:
        raise SessionError(
            exc.code,
            exc.message,
            1008,
            retryable=False,
            action=exc.action,
        ) from exc
    return api_key_row, user, extension_id, extension_version


@router.websocket("/api/v1/extension/ws")
async def extension_websocket(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    gateway: ExtensionGateway = websocket.app.state.extension_gateway
    requested_protocols = websocket.scope.get("subprotocols", [])
    selected_protocol = WS_SUBPROTOCOL if WS_SUBPROTOCOL in requested_protocols else None
    await websocket.accept(subprotocol=selected_protocol)
    if selected_protocol is None:
        error = _malformed("Missing the abm.v1 WebSocket subprotocol.")
        await websocket.send_json(error_envelope(error))
        await websocket.close(code=error.close_code, reason=error.code)
        return

    peer: GatewayPeer | None = None
    heartbeat_task: asyncio.Task | None = None
    try:
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=settings.hello_timeout_ms / 1000,
            )
        except TimeoutError:
            error = SessionError(
                "ABM_HELLO_TIMEOUT",
                "session.hello was not sent in time.",
                1013,
                retryable=True,
                action="wait",
            )
            await websocket.send_json(error_envelope(error))
            await websocket.close(code=error.close_code, reason=error.code)
            return

        hello = _parse_message(raw)
        api_key_row, user, extension_id, extension_version = await _authenticate_hello(
            websocket, hello
        )
        now = datetime.now(UTC)
        hello_payload = hello.get("payload") or {}
        browser_id = hello_payload.get("browserId")
        if not isinstance(browser_id, str) or not browser_id.strip():
            browser_id = None
        capabilities = hello_payload.get("capabilities")
        if not isinstance(capabilities, dict):
            capabilities = {}
        peer = GatewayPeer(
            websocket=websocket,
            api_key_id=api_key_row.id,
            user_id=user.id,
            extension_id=extension_id,
            extension_version=extension_version,
            connected_at=now,
            last_seen=now,
            connection_id=gateway.connection_id_for(api_key_row.id, browser_id),
            browser_id=browser_id,
            capabilities=capabilities,
        )
        try:
            await gateway.register(peer)
        except GatewayCallError as exc:
            await gateway.send_error_and_close(
                peer,
                SessionError(
                    exc.code,
                    exc.message,
                    1008,
                    retryable=exc.retryable,
                    action=exc.action,
                ),
            )
            return
        await peer.send(
            envelope(
                "session.ready",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "extensionId": extension_id,
                    "account": {
                        "id": user.id,
                        "displayName": user.display_name,
                        "planCode": tier_for(user, settings),
                    },
                    "apiKeyId": api_key_row.id,
                    "connectionId": peer.connection_id,
                    "browserId": peer.browser_id,
                    "capabilities": peer.capabilities,
                    "serverTime": now.isoformat(),
                },
                message_id=f"ready_{uuid4().hex}",
            )
        )
        heartbeat_task = asyncio.create_task(gateway.heartbeat_loop(peer))

        while peer.active:
            raw = await websocket.receive_text()
            peer.last_seen = datetime.now(UTC)
            try:
                message = _parse_message(raw)
            except SessionError as error:
                await gateway.send_error_and_close(peer, error)
                break
            message_type = message["type"]
            if message_type == "session.pong":
                continue
            if message_type == "session.ping":
                await peer.send(envelope("session.pong"))
                continue
            if message_type == "session.identify":
                new_extension_id = message["payload"].get("extensionId")
                if isinstance(new_extension_id, str) and new_extension_id:
                    await gateway.update_extension_id(peer, new_extension_id)
                continue
            if message_type == "tool.result":
                await gateway.accept_tool_result(
                    connection_id=peer.connection_id,
                    message_id=message.get("id"),
                    payload=message["payload"],
                )
                continue
            await gateway.send_error_and_close(
                peer,
                SessionError(
                    "ABM_PROTOCOL_ERROR",
                    f"Extensions must not send {message_type}.",
                    1008,
                    action="upgrade_extension",
                ),
            )
            break
    except WebSocketDisconnect:
        pass
    except SessionError as error:
        if peer is not None:
            await gateway.send_error_and_close(peer, error)
        else:
            try:
                await websocket.send_json(error_envelope(error))
                await websocket.close(code=error.close_code, reason=error.code)
            except Exception:
                logger.debug("Failed to send handshake error", exc_info=True)
    except Exception:
        logger.exception("Extension WebSocket failed")
        if peer is not None:
            await gateway.send_error_and_close(
                peer,
                SessionError(
                    "ABM_INTERNAL_ERROR",
                    "Internal gateway error.",
                    1011,
                    retryable=True,
                    action="wait",
                ),
            )
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        if peer is not None:
            was_current = gateway.get_peer(peer.connection_id) is peer
            await gateway.unregister(peer)
            if was_current:
                with contextlib.suppress(Exception):
                    await websocket.app.state.notification_service.create(
                        user_id=peer.user_id,
                        kind="extension_offline",
                        title="Browser extension offline",
                        body=(
                            "An extension connection closed. Reconnect it from "
                            "the browser extension popup."
                        ),
                        action_url="/console",
                        dedupe_minutes=60,
                    )
