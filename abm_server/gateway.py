"""Backward-compatible re-export for the extension gateway."""

from .extension_gateway.gateway import ExtensionGateway, GatewayCallError, GatewayPeer, PendingCall

__all__ = ["ExtensionGateway", "GatewayCallError", "GatewayPeer", "PendingCall"]
