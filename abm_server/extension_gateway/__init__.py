"""Chrome extension WebSocket gateway and protocol contract."""

from .gateway import ExtensionGateway, GatewayCallError, GatewayPeer, PendingCall
from .protocol import (
    MESSAGE_TYPES,
    PROTOCOL_VERSION,
    WS_SUBPROTOCOL,
    SessionError,
    envelope,
    error_envelope,
    error_payload,
    validate_envelope,
)

__all__ = [
    "MESSAGE_TYPES",
    "PROTOCOL_VERSION",
    "WS_SUBPROTOCOL",
    "ExtensionGateway",
    "GatewayCallError",
    "GatewayPeer",
    "PendingCall",
    "SessionError",
    "envelope",
    "error_envelope",
    "error_payload",
    "validate_envelope",
]
