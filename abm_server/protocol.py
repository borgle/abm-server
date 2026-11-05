"""Backward-compatible re-export for the WebSocket protocol contract."""

from .extension_gateway.protocol import (
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
    "SessionError",
    "envelope",
    "error_envelope",
    "error_payload",
    "validate_envelope",
]
