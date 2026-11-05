from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = "abm/1"
WS_SUBPROTOCOL = "abm.v1"

MESSAGE_TYPES = frozenset(
    {
        "session.hello",
        "session.ready",
        "session.identify",
        "session.ping",
        "session.pong",
        "tool.invoke",
        "tool.result",
        "notice.push",
        "error",
    }
)


@dataclass(slots=True)
class SessionError(Exception):
    code: str
    message: str
    close_code: int
    retryable: bool = False
    action: str = "none"

    def __str__(self) -> str:
        return self.message


def envelope(
    message_type: str,
    payload: dict[str, Any] | None = None,
    *,
    message_id: str | None = None,
) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "id": message_id,
        "type": message_type,
        "payload": payload or {},
    }


def error_payload(error: SessionError) -> dict[str, Any]:
    return {
        "code": error.code,
        "message": error.message,
        "retryable": error.retryable,
        "action": error.action,
    }


def error_envelope(error: SessionError, *, message_id: str | None = None) -> dict[str, Any]:
    return envelope("error", error_payload(error), message_id=message_id)


def validate_envelope(message: object) -> str:
    if not isinstance(message, dict):
        raise SessionError(
            "ABM_PROTOCOL_ERROR",
            "WebSocket message must be a JSON object.",
            1008,
            action="upgrade_extension",
        )
    if message.get("v") != PROTOCOL_VERSION:
        raise SessionError(
            "ABM_PROTOCOL_ERROR",
            "Unsupported protocol version.",
            1008,
            action="upgrade_extension",
        )
    message_type = message.get("type")
    if not isinstance(message_type, str) or message_type not in MESSAGE_TYPES:
        raise SessionError(
            "ABM_PROTOCOL_ERROR",
            "Unknown WebSocket message type.",
            1008,
            action="upgrade_extension",
        )
    if not isinstance(message.get("payload"), dict):
        raise SessionError(
            "ABM_PROTOCOL_ERROR",
            "WebSocket payload must be a JSON object.",
            1008,
            action="upgrade_extension",
        )
    return message_type
