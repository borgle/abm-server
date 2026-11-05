from __future__ import annotations

from typing import Any

from mcp import types

from ..tools.browser import BROWSER_TOOLS

_STATUS_VALUES = ["pending", "active", "rejected", "disabled"]
_PLAN_VALUES = ["free", "pro"]


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> types.Tool:
    return types.Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
    )


ACCOUNT_TOOLS: tuple[types.Tool, ...] = (
    _tool(
        "account_register",
        "Submit an ABM account registration request. This public tool requires no "
        "existing credentials and does not reveal whether the email already exists.",
        {
            "email": {"type": "string", "format": "email"},
            "password": {"type": "string", "minLength": 10},
            "displayName": {"type": "string", "minLength": 1, "maxLength": 120},
            "applicationNote": {"type": "string", "maxLength": 2000},
        },
        ["email", "password", "displayName"],
    ),
    _tool(
        "account_me",
        "Read the account, plan, active key count, and extension connection status "
        "for the current MCP credential.",
    ),
    _tool(
        "account_update_profile",
        "Update the display name of the current account.",
        {
            "displayName": {"type": "string", "minLength": 1, "maxLength": 120},
        },
        ["displayName"],
    ),
    _tool(
        "account_change_password",
        "Change the current account password. This revokes other account sessions "
        "and OAuth credentials.",
        {
            "currentPassword": {"type": "string", "minLength": 1},
            "newPassword": {"type": "string", "minLength": 10},
        },
        ["currentPassword", "newPassword"],
    ),
    _tool(
        "api_key_list",
        "List API Key metadata for the current account without returning key secrets.",
    ),
    _tool(
        "api_key_create",
        "Create an API Key for the current account and return the secret once in this response.",
        {
            "name": {"type": "string", "minLength": 1, "maxLength": 120},
        },
        ["name"],
    ),
    _tool(
        "api_key_revoke",
        "Revoke an API Key for the current account and close extension connections using it.",
        {
            "keyId": {"type": "string", "minLength": 1},
        },
        ["keyId"],
    ),
)


ADMIN_TOOLS: tuple[types.Tool, ...] = (
    _tool(
        "admin_list_users",
        "List accounts as an administrator, optionally filtered by status and keyword. "
        "Requires an administrator account.",
        {
            "status": {"type": "string", "enum": _STATUS_VALUES},
            "q": {"type": "string", "maxLength": 120},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
        },
    ),
    _tool(
        "admin_update_user",
        "Update an account's status, plan, plan expiry, or note as an administrator. "
        "Requires an administrator account.",
        {
            "userId": {"type": "string", "minLength": 1},
            "status": {"type": "string", "enum": _STATUS_VALUES},
            "planCode": {"type": "string", "enum": _PLAN_VALUES},
            "planExpiresAt": {
                "type": ["string", "null"],
                "description": "ISO 8601 timestamp; pass null to clear the expiry.",
            },
            "reason": {"type": "string", "maxLength": 1000},
        },
        ["userId"],
    ),
    _tool(
        "admin_get_settings",
        "Read system settings as an administrator. Requires an administrator account.",
    ),
    _tool(
        "admin_update_settings",
        "Update the registration approval policy as an administrator. "
        "Requires an administrator account.",
        {
            "registrationRequireApproval": {"type": "boolean"},
        },
        ["registrationRequireApproval"],
    ),
    _tool(
        "admin_list_audit",
        "Read account audit events as an administrator. Requires an administrator account.",
        {
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        },
    ),
)

PUBLIC_TOOLS: tuple[types.Tool, ...] = (ACCOUNT_TOOLS[0],)
AUTHENTICATED_TOOLS: tuple[types.Tool, ...] = BROWSER_TOOLS + ACCOUNT_TOOLS
ALL_TOOLS: tuple[types.Tool, ...] = AUTHENTICATED_TOOLS + ADMIN_TOOLS

PUBLIC_TOOL_BY_NAME = {tool.name: tool for tool in PUBLIC_TOOLS}
AUTHENTICATED_TOOL_BY_NAME = {tool.name: tool for tool in AUTHENTICATED_TOOLS}
ADMIN_TOOL_BY_NAME = {tool.name: tool for tool in ADMIN_TOOLS}
TOOL_BY_NAME = {tool.name: tool for tool in ALL_TOOLS}

# Compatibility aliases for existing callers and tests.
TOOLS = AUTHENTICATED_TOOLS
