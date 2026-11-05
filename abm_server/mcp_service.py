"""Backward-compatible re-export for the MCP service."""

from .mcp.service import McpPathMiddleware, McpService, runtime_auth_var

__all__ = ["McpPathMiddleware", "McpService", "runtime_auth_var"]
