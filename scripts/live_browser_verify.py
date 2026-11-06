from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def result_json(result) -> dict:
    text = result.content[0].text if result.content else ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


async def main() -> int:
    api_key = os.environ.get("ABM_API_KEY", "").strip()
    server = os.environ.get("ABM_SERVER_URL", "https://abm.borgle.io").rstrip("/")
    native_file = os.environ.get("ABM_NATIVE_FILE", "").strip()
    if not api_key:
        print("ABM_API_KEY is required", file=sys.stderr)
        return 2

    tab_id: int | None = None
    failures = 0

    async def call(session: ClientSession, name: str, arguments: dict) -> dict:
        nonlocal failures
        result = await session.call_tool(name, arguments)
        if result.isError:
            failures += 1
            print(f"FAIL {name}: {result.content[0].text if result.content else 'unknown error'}")
            return {}
        payload = result_json(result)
        print(f"PASS {name}")
        return payload

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
        tools = await session.list_tools()
        names = sorted(tool.name for tool in tools.tools)
        print(f"PASS tools/list ({len(names)} tools)")
        if len(names) != 21 or any(not name.startswith("browser_") for name in names):
            print(f"FAIL unexpected tool catalog: {names}")
            return 1

        try:
            navigated = await call(
                session,
                "browser_navigate",
                {
                    "url": "https://borgle.io",
                    "waitUntil": "domcontentloaded",
                    "timeout": 30000,
                    "background": True,
                },
            )
            if not navigated.get("success"):
                return 1
            tab_id = int(navigated["tabId"])

            await call(
                session,
                "browser_wait_elements",
                {
                    "selector": "body",
                    "count": 1,
                    "timeout": 10000,
                    "tabId": tab_id,
                },
            )
            injected = await call(
                session,
                "browser_inject_script",
                {
                    "tabId": tab_id,
                    "code": """
                          const input = document.createElement('input');
                          input.id = 'abm-live-input';
                          input.style.cssText = 'position:fixed;left:10px;top:10px;z-index:999999';
                          const button = document.createElement('button');
                          button.id = 'abm-live-button';
                          button.textContent = 'ABM test';
                          button.style.cssText = 'position:fixed;left:180px;top:10px;'
                            + 'z-index:999999';
                          const output = document.createElement('div');
                          output.id = 'abm-live-output';
                          output.style.cssText = 'position:fixed;left:10px;top:48px;z-index:999999';
                          const fileInput = document.createElement('input');
                          fileInput.id = 'abm-live-files';
                          fileInput.type = 'file';
                          fileInput.multiple = true;
                          const uploadInput = document.createElement('input');
                          uploadInput.id = 'abm-live-upload';
                          uploadInput.type = 'file';
                          const urlFilesInput = document.createElement('input');
                          urlFilesInput.id = 'abm-live-url-files';
                          urlFilesInput.type = 'file';
                          urlFilesInput.multiple = true;
                          const nativeInput = document.createElement('input');
                          nativeInput.id = 'abm-live-native';
                          nativeInput.type = 'file';
                          const videoInput = document.createElement('input');
                          videoInput.id = 'abm-live-video';
                          videoInput.type = 'file';
                          button.addEventListener('click', () => {
                            output.textContent = input.value;
                            window.__abmLiveVerified = true;
                          });
                          document.body.append(
                            input,
                            button,
                            output,
                            fileInput,
                            uploadInput,
                            urlFilesInput,
                            nativeInput,
                            videoInput,
                          );
                          return { installed: true, title: document.title };
                        """,
                },
            )
            if not injected.get("installed"):
                return 1

            await call(
                session,
                "browser_fill",
                {
                    "selector": "#abm-live-input",
                    "value": "ABM live browser test",
                    "method": "set",
                    "timeout": 5000,
                    "tabId": tab_id,
                },
            )
            await call(
                session,
                "browser_keyboard",
                {
                    "selector": "#abm-live-input",
                    "keys": "End",
                    "timeout": 5000,
                    "tabId": tab_id,
                },
            )
            await call(
                session,
                "browser_input_sequence",
                {
                    "events": [
                        {
                            "type": "keyDown",
                            "key": "End",
                            "code": "End",
                            "windowsVirtualKeyCode": 35,
                        },
                        {
                            "type": "keyUp",
                            "key": "End",
                            "code": "End",
                            "windowsVirtualKeyCode": 35,
                        },
                    ],
                    "tabId": tab_id,
                },
            )
            await call(
                session,
                "browser_click",
                {
                    "selector": "#abm-live-button",
                    "timeout": 5000,
                    "tabId": tab_id,
                },
            )
            await call(
                session,
                "browser_mouse_click",
                {"x": 220, "y": 24, "tabId": tab_id},
            )
            extracted = await call(
                session,
                "browser_extract_data",
                {
                    "selector": "#abm-live-output",
                    "source": "element",
                    "attribute": "text",
                    "timeout": 5000,
                    "tabId": tab_id,
                },
            )
            if extracted.get("data") != "ABM live browser test":
                print(f"FAIL extracted text: {extracted}")
                failures += 1

            await call(
                session,
                "browser_control",
                {"action": "activate_tab", "params": {"tabId": tab_id}},
            )
            await asyncio.sleep(0.5)
            await call(
                session,
                "browser_read_page_data",
                {"path": "document.title"},
            )
            await call(
                session,
                "browser_set_files",
                {
                    "selector": "#abm-live-files",
                    "files": [
                        {
                            "base64Data": base64.b64encode(b"ABM upload test").decode(),
                            "fileName": "abm-live.txt",
                            "mimeType": "text/plain",
                        }
                    ],
                    "tabId": tab_id,
                },
            )
            await call(
                session,
                "browser_upload_file",
                {
                    "selector": "#abm-live-upload",
                    "base64Data": base64.b64encode(b"ABM single upload").decode(),
                    "fileName": "abm-live-single.txt",
                    "mimeType": "text/plain",
                    "tabId": tab_id,
                },
            )
            await call(
                session,
                "browser_set_files_from_urls",
                {
                    "selector": "#abm-live-url-files",
                    "urls": [
                        {
                            "url": "https://abm.borgle.io/static/app.css",
                            "fileName": "abm-live.css",
                            "mimeType": "text/css",
                        }
                    ],
                    "tabId": tab_id,
                    "timeout": 15000,
                },
            )
            if native_file:
                native_path = Path(native_file).resolve()
                if not native_path.is_file():
                    raise RuntimeError(f"native test file not found: {native_path}")
                await call(
                    session,
                    "browser_set_files_native",
                    {
                        "selector": "#abm-live-native",
                        "paths": [str(native_path)],
                        "timeout": 15000,
                        "tabId": tab_id,
                    },
                )
                native_info = await call(
                    session,
                    "browser_inject_script",
                    {
                        "tabId": tab_id,
                        "code": """
                          const file = document.querySelector('#abm-live-native')?.files?.[0];
                          return file ? { name: file.name, size: file.size } : null;
                        """,
                    },
                )
                if (
                    native_info.get("name") != native_path.name
                    or native_info.get("size") != native_path.stat().st_size
                ):
                    raise RuntimeError(f"native file input mismatch: {native_info}")
            await call(
                session,
                "browser_network_intercept",
                {"cmd": "start", "tabId": tab_id},
            )
            await call(
                session,
                "browser_network_intercept",
                {"cmd": "stop", "tabId": tab_id},
            )
            staged = await call(
                session,
                "browser_stage_video",
                {
                    "fileName": "abm-live.mp4",
                    "fileType": "video/mp4",
                    "base64": base64.b64encode(b"ABM video test").decode(),
                    "delivery": "url",
                    "timeoutMs": 15000,
                },
            )
            if staged.get("status") != "delivered":
                print(f"FAIL video staging: {staged}")
                failures += 1
            await call(
                session,
                "browser_set_video_to_page",
                {
                    "selector": "#abm-live-video",
                    "timeout": 10000,
                    "tabId": tab_id,
                },
            )
            await call(
                session,
                "browser_mouse_scroll",
                {"deltaY": 120, "steps": 2, "tabId": tab_id},
            )
            await call(
                session,
                "browser_control",
                {"action": "get_tab", "params": {"tabId": tab_id}},
            )
        finally:
            if tab_id is not None:
                await call(
                    session,
                    "browser_control",
                    {"action": "close_tab", "params": {"tabId": tab_id}},
                )

    if failures:
        print(f"{failures} live checks failed")
        return 1
    print("All live browser checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
