from __future__ import annotations

from typing import Any

from mcp import types


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    *,
    session: bool = True,
) -> types.Tool:
    all_properties = dict(properties or {})
    if session:
        all_properties["browserSessionId"] = {
            "type": "string",
            "description": "Handle returned by browser_open_session.",
        }
    return types.Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": all_properties,
            "required": required or [],
            "additionalProperties": False,
        },
    )


_selector = {"type": "string", "description": "CSS selector."}
_tab_id = {"type": "integer", "description": "Target tab ID. Defaults to the active tab."}
_timeout = {"type": "integer", "description": "Timeout in milliseconds."}


TOOLS: tuple[types.Tool, ...] = (
    _tool(
        "browser_inject_script",
        "Execute JavaScript in the page's main world. Falls back to CDP when the page "
        "CSP blocks eval; MV3 isolated worlds cannot execute arbitrary source strings.",
        {
            "code": {
                "type": "string",
                "description": "Function body source. Read arguments from args.",
            },
            "args": {"type": "object", "description": "Arguments passed to the injected script."},
            "tabId": _tab_id,
        },
        ["code"],
    ),
    _tool(
        "browser_read_page_data",
        "Read a value at a dot-separated path on window.",
        {
            "path": {"type": "string", "description": "Dot-separated path under window."},
            "tabId": _tab_id,
        },
        ["path"],
    ),
    _tool(
        "browser_navigate",
        "Navigate to a URL, optionally waiting for load or reusing a tab. "
        "Reuse scope is derived from the target URL.",
        {
            "url": {"type": "string"},
            "waitUntil": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle"]},
            "timeout": _timeout,
            "reuse": {
                "type": ["boolean", "string"],
                "enum": [True, False, "site", "origin"],
                "default": True,
                "description": (
                    'Tab reuse policy. true or "site" (default): reuse a tab on the same host, '
                    "ignoring www./m./mobile. prefixes, but never across subdomains; "
                    '"origin": reuse only when protocol, host, and port all match; '
                    "false: always open a new tab."
                ),
            },
            "reuseKey": {
                "type": "string",
                "description": (
                    "Explicit working-tab name. The same key always resolves to the same tab; "
                    "if the tab is closed, it is recreated using the site rule."
                ),
            },
            "automationGroupCollapsed": {"type": "boolean"},
            "background": {"type": "boolean"},
        },
        ["url"],
    ),
    _tool(
        "browser_control",
        "Manage browser tabs: close, get, update, query, or activate.",
        {
            "action": {
                "type": "string",
                "enum": [
                    "close_tab",
                    "get_tab",
                    "update_tab",
                    "query_tabs",
                    "activate_tab",
                    "close_group",
                ],
            },
            "params": {"type": "object"},
        },
        ["action", "params"],
    ),
    _tool(
        "browser_extract_data",
        "Extract data from an element, window, or document.",
        {
            "selector": _selector,
            "path": {"type": "string"},
            "attribute": {"type": "string"},
            "source": {"type": "string", "enum": ["element", "window", "document"]},
            "all": {"type": "boolean"},
            "timeout": _timeout,
            "tabId": _tab_id,
        },
    ),
    _tool(
        "browser_click",
        "Click an element by selector or visible text.",
        {
            "selector": _selector,
            "text": {"type": "string"},
            "timeout": _timeout,
            "waitClickable": {"type": "boolean"},
            "tabId": _tab_id,
        },
        ["selector"],
    ),
    _tool(
        "browser_fill",
        "Fill an input, textarea, or contenteditable element.",
        {
            "selector": _selector,
            "value": {"type": "string"},
            "method": {"type": "string", "enum": ["set", "type", "execCommand"]},
            "clearBefore": {"type": "boolean"},
            "timeout": _timeout,
            "tabId": _tab_id,
        },
        ["selector", "value"],
    ),
    _tool(
        "browser_keyboard",
        "Send keyboard input to the focused element.",
        {
            "keys": {"type": "string"},
            "selector": _selector,
            "delay": {"type": "integer"},
            "timeout": _timeout,
            "tabId": _tab_id,
        },
        ["keys"],
    ),
    _tool(
        "browser_upload_file",
        "Inject a single base64 file into a file input.",
        {
            "selector": _selector,
            "base64Data": {"type": "string"},
            "fileName": {"type": "string"},
            "mimeType": {"type": "string"},
            "timeout": _timeout,
            "tabId": _tab_id,
        },
        ["selector", "base64Data"],
    ),
    _tool(
        "browser_set_files",
        "Inject multiple base64 files into a file input.",
        {
            "selector": _selector,
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "base64Data": {"type": "string"},
                        "fileName": {"type": "string"},
                        "mimeType": {"type": "string"},
                    },
                    "required": ["base64Data", "fileName"],
                },
            },
            "timeout": _timeout,
            "tabId": _tab_id,
        },
        ["selector", "files"],
    ),
    _tool(
        "browser_set_files_from_urls",
        "Download files from URLs and inject them into a file input.",
        {
            "selector": _selector,
            "urls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "fileName": {"type": "string"},
                        "mimeType": {"type": "string"},
                    },
                    "required": ["url"],
                },
            },
            "tabId": _tab_id,
            "timeout": _timeout,
        },
        ["selector", "urls"],
    ),
    _tool(
        "browser_wait_elements",
        "Wait until the page contains the requested number of matching elements.",
        {
            "selector": _selector,
            "count": {"type": "integer"},
            "timeout": _timeout,
            "checkInterval": {"type": "integer"},
            "tabId": _tab_id,
        },
        ["selector", "count"],
    ),
    _tool(
        "browser_set_video_to_page",
        "Inject a video from the extension staging area into a page file input.",
        {
            "selector": _selector,
            "timeout": _timeout,
            "clearAfterSet": {"type": "boolean"},
            "tabId": _tab_id,
        },
        ["selector"],
    ),
    _tool(
        "browser_download_video_from_url",
        "Download a video URL and stage it in the extension.",
        {
            "url": {"type": "string"},
            "timeout": _timeout,
            "tabId": _tab_id,
        },
        ["url"],
    ),
    _tool(
        "browser_network_intercept",
        "Capture, filter, and read network requests through CDP.",
        {
            "cmd": {"type": "string", "enum": ["start", "stop", "list", "detail"]},
            "tabId": _tab_id,
            "filter": {"type": "string"},
            "requestId": {"type": "string"},
            "compress": {"type": "boolean"},
        },
        ["cmd"],
    ),
    _tool(
        "browser_mouse_click",
        "Dispatch a CDP mouse click.",
        {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "clickCount": {"type": "integer"},
            "pressDurationMs": {"type": "integer"},
            "tabId": _tab_id,
        },
        ["x", "y"],
    ),
    _tool(
        "browser_mouse_scroll",
        "Dispatch a CDP mouse wheel scroll.",
        {
            "deltaX": {"type": "integer"},
            "deltaY": {"type": "integer"},
            "steps": {"type": "integer"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "intervalMs": {"type": "integer"},
            "tabId": _tab_id,
        },
        ["deltaY"],
    ),
    _tool(
        "browser_input_sequence",
        "Replay a sequence of CDP mouse, keyboard, and text input events.",
        {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "mouseMoved",
                                "mousePressed",
                                "mouseReleased",
                                "mouseWheel",
                                "keyDown",
                                "keyUp",
                                "rawKeyDown",
                                "char",
                                "insertText",
                            ],
                        },
                        "after": {"type": "integer"},
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "button": {"type": "string"},
                        "clickCount": {"type": "integer"},
                        "modifiers": {"type": "integer"},
                        "key": {"type": "string"},
                        "code": {"type": "string"},
                        "text": {"type": "string"},
                        "windowsVirtualKeyCode": {"type": "integer"},
                        "deltaX": {"type": "integer"},
                        "deltaY": {"type": "integer"},
                    },
                    "required": ["type"],
                },
            },
            "tabId": _tab_id,
        },
        ["events"],
    ),
    _tool(
        "browser_set_files_native",
        "Inject local absolute-path files into a file input through CDP. "
        "Preferred for large local files because bytes stay on the user's machine.",
        {
            "selector": _selector,
            "paths": {"type": "array", "items": {"type": "string"}},
            "timeout": _timeout,
            "tabId": _tab_id,
        },
        ["selector", "paths"],
    ),
    _tool(
        "browser_stage_video",
        "Stage a base64 or URL video in the extension. URL delivery downloads "
        "directly from the source and does not store video on the server. For files "
        "already on the user's machine, prefer browser_set_files_native.",
        {
            "fileName": {"type": "string"},
            "fileType": {"type": "string"},
            "base64": {"type": "string"},
            "url": {"type": "string"},
            "delivery": {"type": "string", "enum": ["bridge", "url", "auto"]},
            "tabId": _tab_id,
            "timeoutMs": {"type": "integer"},
        },
        ["fileName"],
    ),
    _tool(
        "browser_send_notice",
        "Push a notification to the online extension bound to the current API Key.",
        {
            "title": {"type": "string"},
            "level": {"type": "string", "enum": ["info", "warning"]},
            "body": {"type": "string"},
            "actionUrl": {"type": "string"},
        },
        ["title"],
    ),
    _tool(
        "browser_open_session",
        "Open an isolated browser task session and acquire a connection lease.",
        {
            "connectionId": {
                "type": "string",
                "description": "Optional browser connection id. Picks that browser when online.",
            },
            "ttlSeconds": {"type": "integer"},
            "groupTitle": {
                "type": "string",
                "description": "Visible tab group title, e.g. 'Research: apartments'.",
            },
            "collapsed": {
                "type": "boolean",
                "description": "Collapse the task tab group. Use false when a human must watch.",
            },
            "priority": {
                "type": "integer",
                "description": "Task priority; publishing may reserve a slot and preempt research.",
            },
        },
        session=False,
    ),
    _tool(
        "browser_close_session",
        "Close a browser task session and release its connection lease.",
        {
            "browserSessionId": {
                "type": "string",
                "description": "Handle returned by browser_open_session.",
            }
        },
        ["browserSessionId"],
        session=False,
    ),
)

TOOL_BY_NAME = {tool.name: tool for tool in TOOLS}

BROWSER_TOOLS = TOOLS
BROWSER_TOOL_BY_NAME = TOOL_BY_NAME

__all__ = ["BROWSER_TOOLS", "BROWSER_TOOL_BY_NAME", "TOOLS", "TOOL_BY_NAME"]
