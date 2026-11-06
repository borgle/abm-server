from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def payload(result) -> dict:
    text = result.content[0].text if result.content else ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


async def main() -> int:
    api_key = os.environ.get("ABM_API_KEY", "").strip()
    server = os.environ.get("ABM_SERVER_URL", "https://abm.borgle.io").rstrip("/")
    file_path = Path(os.environ.get("ABM_VIDEO_FILE", "build/abm-bridge-test.mp4")).resolve()
    if not api_key:
        print("ABM_API_KEY is required", file=sys.stderr)
        return 2
    if not file_path.is_file():
        print(f"video file not found: {file_path}", file=sys.stderr)
        return 2

    video_bytes = file_path.read_bytes()
    bridge_tab: int | None = None
    test_tab: int | None = None

    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120,
        ) as http_client,
        streamable_http_client(f"{server}/mcp", http_client=http_client) as (
            read_stream,
            write_stream,
            _,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        async def call(name: str, arguments: dict) -> dict:
            result = await session.call_tool(name, arguments)
            if result.isError:
                message = result.content[0].text if result.content else "unknown error"
                raise RuntimeError(f"{name}: {message}")
            return payload(result)

        try:
            tab_list = await call(
                "browser_control",
                {"action": "query_tabs", "params": {"queryInfo": {}}},
            )
            bridge_tabs = [
                tab
                for tab in tab_list.get("tabs", [])
                if "/video-bridge" in str(tab.get("url") or "")
            ]
            bridge_url = f"{server}/video-bridge?verify={int(time.time())}"
            if bridge_tabs:
                bridge_tab = int(bridge_tabs[0]["id"])
                for duplicate in bridge_tabs[1:]:
                    if duplicate.get("id") is not None:
                        await call(
                            "browser_control",
                            {
                                "action": "close_tab",
                                "params": {"tabId": int(duplicate["id"])},
                            },
                        )
                await call(
                    "browser_control",
                    {
                        "action": "update_tab",
                        "params": {
                            "tabId": bridge_tab,
                            "updateInfo": {"url": bridge_url, "active": True},
                        },
                    },
                )
                await asyncio.sleep(2)
            else:
                bridge_nav = await call(
                    "browser_navigate",
                    {
                        "url": bridge_url,
                        "waitUntil": "domcontentloaded",
                        "timeout": 30000,
                    },
                )
                bridge_tab = int(bridge_nav["tabId"])

            bridge_state = {}
            for _ in range(20):
                await asyncio.sleep(0.5)
                bridge_state = await call(
                    "browser_inject_script",
                    {
                        "tabId": bridge_tab,
                        "code": """
                          return {
                            apiKey: document.querySelector('#bridge-key')?.value || '',
                            extensionId: document.querySelector('#bridge-extension')?.value || '',
                            state: document.querySelector('#bridge-state')?.textContent || '',
                            meta: document.querySelector('#bridge-meta')?.textContent || ''
                          };
                        """,
                    },
                )
                if bridge_state.get("apiKey") and bridge_state.get("extensionId"):
                    break

            print(
                "bridge auto-config:",
                json.dumps(
                    {
                        "hasApiKey": bool(bridge_state.get("apiKey")),
                        "extensionId": bridge_state.get("extensionId"),
                        "state": bridge_state.get("state"),
                        "meta": bridge_state.get("meta"),
                    },
                    ensure_ascii=False,
                ),
            )
            if not bridge_state.get("apiKey") or not bridge_state.get("extensionId"):
                raise RuntimeError("video bridge did not auto-configure")

            test_nav = await call(
                "browser_navigate",
                {
                    "url": "https://borgle.io",
                    "waitUntil": "domcontentloaded",
                    "timeout": 30000,
                    "background": True,
                },
            )
            test_tab = int(test_nav["tabId"])
            await call(
                "browser_inject_script",
                {
                    "tabId": test_tab,
                    "code": """
                      const input = document.createElement('input');
                      input.id = 'abm-bridge-video-input';
                      input.type = 'file';
                      input.style.cssText = 'position:fixed;z-index:999999;left:10px;top:10px';
                      document.body.appendChild(input);
                      return { installed: true };
                    """,
                },
            )

            staged = await call(
                "browser_stage_video",
                {
                    "fileName": file_path.name,
                    "fileType": "video/mp4",
                    "base64": base64.b64encode(video_bytes).decode("ascii"),
                    "delivery": "bridge",
                    "timeoutMs": 60000,
                },
            )
            print("bridge video delivery:", json.dumps(staged, ensure_ascii=False))
            if staged.get("status") != "delivered" or staged.get("fileSize") != len(video_bytes):
                raise RuntimeError("bridge video delivery result mismatch")

            injected = await call(
                "browser_set_video_to_page",
                {
                    "selector": "#abm-bridge-video-input",
                    "timeout": 15000,
                    "tabId": test_tab,
                },
            )
            print("video input injection:", json.dumps(injected, ensure_ascii=False))

            file_info = await call(
                "browser_inject_script",
                {
                    "tabId": test_tab,
                    "code": """
                      const file = document.querySelector('#abm-bridge-video-input')?.files?.[0];
                      return file ? { name: file.name, size: file.size, type: file.type } : null;
                    """,
                },
            )
            print("browser file input:", json.dumps(file_info, ensure_ascii=False))
            if (
                file_info.get("name") != file_path.name
                or file_info.get("size") != len(video_bytes)
                or file_info.get("type") != "video/mp4"
            ):
                raise RuntimeError("browser file input mismatch")

            bridge_log = await call(
                "browser_inject_script",
                {
                    "tabId": bridge_tab,
                    "code": "return document.querySelector('#bridge-log')?.textContent || '';",
                },
            )
            if "投递完成" not in str(bridge_log):
                raise RuntimeError(f"bridge completion not visible in log: {bridge_log}")
            print("bridge completion log: PASS")
            print(f"LOCAL VIDEO BRIDGE TEST PASSED ({len(video_bytes)} bytes)")
            return 0
        finally:
            if test_tab is not None:
                try:
                    await call(
                        "browser_control",
                        {"action": "close_tab", "params": {"tabId": test_tab}},
                    )
                except Exception as error:
                    print(f"cleanup test tab failed: {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
