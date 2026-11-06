"""Xiaohongshu card renderer (Playwright).

Markdown blocks are paginated inside the page: each block is appended to the
current card and moved to a new card when it no longer fits. Rendering happens
in Chromium because it reuses the same CSS typography as the web UI and handles
CJK line breaking correctly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from ..errors import ApiError
from .layout import Block

_STYLES: dict[str, dict[str, str]] = {
    "xhs-paper": {
        "bg": "#f7f6f0",
        "ink": "#10110f",
        "muted": "#6f7266",
        "accent": "#d8ff3e",
        "line": "rgba(16,17,15,.12)",
        "panel": "rgba(255,255,255,.72)",
    },
    "xhs-ink": {
        "bg": "#10110f",
        "ink": "#f4f4ed",
        "muted": "#a9ac9d",
        "accent": "#d8ff3e",
        "line": "rgba(244,244,237,.16)",
        "panel": "rgba(255,255,255,.06)",
    },
    "xhs-grid": {
        "bg": "#f2f2eb",
        "ink": "#10110f",
        "muted": "#6f7266",
        "accent": "#10110f",
        "line": "rgba(16,17,15,.14)",
        "panel": "rgba(255,255,255,.6)",
    },
}

_ALLOWED_STYLES = set(_STYLES)

_SEMAPHORE: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(1)
    return _SEMAPHORE


@dataclass(slots=True)
class CardDocument:
    title: str
    subtitle: str
    blocks: list[Block]
    style_id: str = "xhs-paper"
    include_cover: bool = True
    show_page_number: bool = True
    cover_image: str = ""


def _block_json(block: Block) -> dict[str, Any]:
    return {
        "type": block.type,
        "html": block.html,
        "level": block.level,
        "ordered": block.ordered,
        "index": block.index,
        "text": block.text,
        "lang": block.lang,
        "src": block.src,
        "alt": block.alt,
    }


def _card_html(document: CardDocument) -> str:
    theme = _STYLES.get(document.style_id, _STYLES["xhs-paper"])
    payload = {
        "title": document.title,
        "subtitle": document.subtitle,
        "blocks": [_block_json(block) for block in document.blocks],
        "theme": theme,
        "styleId": document.style_id,
        "includeCover": document.include_cover,
        "showPageNumber": document.show_page_number,
        "coverImage": document.cover_image,
    }
    import json

    data = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8" />
<style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #e9e9e1; }}
body {{ font-family: "Noto Sans SC", "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; }}
.card {{
  width: 1080px; height: 1440px; padding: 84px 82px 66px;
  background: var(--bg); color: var(--ink);
  display: flex; flex-direction: column; position: relative; overflow: hidden;
  margin: 0 auto;
}}
.card + .card {{ margin-top: 40px; }}
.brand {{
  display: flex; align-items: center; justify-content: space-between;
  font-size: 24px; color: var(--muted); letter-spacing: .08em;
}}
.pill {{
  background: var(--ink); color: var(--accent); padding: 8px 16px;
  border-radius: 999px; font-size: 20px; font-weight: 700; letter-spacing: .16em;
}}
.card.dark .pill {{ background: var(--accent); color: var(--ink); }}
.headline {{
  margin: 42px 0 0; font-size: 78px; line-height: 1.16;
  font-weight: 800; letter-spacing: -.01em;
}}
.subtitle {{ margin-top: 22px; font-size: 30px; line-height: 1.6; color: var(--muted); }}
.rule {{ height: 3px; background: var(--ink); margin-top: 34px; width: 96px; }}
.content {{ flex: 1; min-height: 0; overflow: hidden; margin-top: 30px; }}
.flow > :first-child {{ margin-top: 0; }}
.card h2 {{ font-size: 46px; line-height: 1.35; margin: 34px 0 18px; font-weight: 800; }}
.card h3 {{ font-size: 38px; line-height: 1.4; margin: 28px 0 14px; font-weight: 700; }}
.card p {{ font-size: 31px; line-height: 1.78; margin: 0 0 22px; }}
.card ul, .card ol {{ margin: 0 0 22px; padding-left: 34px; }}
.card li {{ font-size: 31px; line-height: 1.75; margin-bottom: 10px; }}
.card blockquote {{
  margin: 0 0 24px; padding: 18px 24px; border-left: 4px solid var(--ink);
  background: var(--panel); font-size: 29px; line-height: 1.7; color: var(--muted);
}}
.card pre {{
  margin: 0 0 24px; padding: 20px 22px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 14px; font-size: 24px;
  line-height: 1.6; white-space: pre-wrap; word-break: break-word;
}}
.card pre code {{ font-family: Menlo, Consolas, monospace; }}
.card table {{ width: 100%; border-collapse: collapse; margin: 0 0 24px; font-size: 25px; }}
.card th, .card td {{ border: 1px solid var(--line); padding: 10px 12px; text-align: left; }}
.card figure {{ margin: 0 0 24px; }}
.card figure img {{ width: 100%; border-radius: 16px; display: block; }}
.card figcaption {{ margin-top: 10px; font-size: 24px; color: var(--muted); text-align: center; }}
.card .item {{ display: flex; gap: 14px; font-size: 31px; line-height: 1.75; margin-bottom: 12px; }}
.card .item .marker {{ color: var(--muted); flex: 0 0 auto; }}
.card .item .body {{ min-width: 0; }}
.card .item .body p {{ margin: 0; }}
.card .item .body ul, .card .item .body ol {{ margin: 6px 0 0; padding-left: 28px; }}
.card hr {{ border: 0; border-top: 2px solid var(--line); margin: 30px 0; }}
.card .placeholder {{
  padding: 26px; border: 2px dashed var(--line); border-radius: 14px;
  color: var(--muted); font-size: 26px; text-align: center;
}}
.footer {{
  display: flex; justify-content: space-between; align-items: center;
  font-size: 22px; color: var(--muted); padding-top: 18px;
}}
.cover .headline {{ font-size: 88px; }}
.cover .content {{ display: flex; flex-direction: column; justify-content: flex-start; }}
.cover .cover-image {{
  margin-top: 40px; border-radius: 22px; overflow: hidden;
  border: 1px solid var(--line);
}}
.cover .cover-image img {{ width: 100%; display: block; }}
.grid-bg {{
  background-image: linear-gradient(var(--line) 1px, transparent 1px),
    linear-gradient(90deg, var(--line) 1px, transparent 1px);
  background-size: 72px 72px;
}}
</style></head>
<body><div id="stage"></div>
<script>
const doc = {data};
const stage = document.getElementById('stage');
const theme = doc.theme;
const MAX_PAGE = 1440;
function styleVars() {{
  return `--bg:${{theme.bg}};--ink:${{theme.ink}};--muted:${{theme.muted}};` +
    `--accent:${{theme.accent}};--line:${{theme.line}};--panel:${{theme.panel}};`;
}}
function el(tag, html, cls) {{
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html !== undefined && html !== null) node.innerHTML = html;
  return node;
}}
function renderBlock(block) {{
  switch (block.type) {{
    case 'heading': {{
      const tag = block.level >= 3 ? 'h3' : 'h2';
      return el(tag, block.html);
    }}
    case 'paragraph': return el('p', block.html);
    case 'list_item': {{
      const item = el('div', '', 'item');
      item.appendChild(el('span', block.ordered ? block.index + '.' : '•', 'marker'));
      item.appendChild(el('div', block.html, 'body'));
      return item;
    }}
    case 'quote': return el('blockquote', block.html);
    case 'code': {{
      const pre = document.createElement('pre');
      const code = document.createElement('code');
      code.textContent = block.text;
      pre.appendChild(code);
      return pre;
    }}
    case 'table': return el('div', block.html);
    case 'image': {{
      if (block.src) {{
        const fig = document.createElement('figure');
        const img = document.createElement('img');
        img.src = block.src;
        fig.appendChild(img);
        if (block.alt) fig.appendChild(el('figcaption', block.alt));
        return fig;
      }}
      return el('div', '[图] ' + (block.alt || ''), 'placeholder');
    }}
    case 'hr': return document.createElement('hr');
    default: return el('div', block.html || '');
  }}
}}
function makeCard(isCover) {{
  const card = el('section', '', 'card' + (isCover ? ' cover' : ''));
  if (doc.theme.bg === '#10110f') card.classList.add('dark');
  if (doc.styleId === 'xhs-grid') card.classList.add('grid-bg');
  card.setAttribute('style', styleVars());
  const brand = el('div', '', 'brand');
  brand.appendChild(el('span', 'ABM', 'pill'));
  brand.appendChild(el('span', isCover ? 'a browser mcp' : '创作台'));
  card.appendChild(brand);
  return card;
}}
const cards = [];
if (doc.includeCover) {{
  const cover = makeCard(true);
  cover.appendChild(el('h1', doc.title, 'headline'));
  if (doc.subtitle) cover.appendChild(el('p', doc.subtitle, 'subtitle'));
  cover.appendChild(el('div', '', 'rule'));
  if (doc.coverImage) {{
    const box = el('div', '', 'cover-image');
    const img = document.createElement('img');
    img.src = doc.coverImage;
    box.appendChild(img);
    cover.appendChild(box);
  }}
  const spacer = el('div', '', 'content');
  cover.appendChild(spacer);
  cover.appendChild(el('div', 'abm · a browser mcp', 'footer'));
  stage.appendChild(cover);
  cards.push(cover);
}}
let card = null;
let content = null;
let flow = null;
let pageNo = 0;
function startPage() {{
  card = makeCard(false);
  content = el('div', '', 'content');
  flow = el('div', '', 'flow');
  content.appendChild(flow);
  card.appendChild(content);
  stage.appendChild(card);
  cards.push(card);
  pageNo += 1;
}}
function finishPage() {{
  if (!card) return;
  const footer = el('div', '', 'footer');
  footer.appendChild(el('span', doc.title.slice(0, 26)));
  footer.appendChild(el('span', doc.showPageNumber ? String(pageNo).padStart(2, '0') : ''));
  card.appendChild(footer);
}}
function fits() {{
  return flow.scrollHeight <= content.clientHeight + 1;
}}
if (doc.blocks.length) {{
  startPage();
  for (const block of doc.blocks) {{
    const node = renderBlock(block);
    flow.appendChild(node);
    if (!fits()) {{
      if (flow.children.length === 1) {{
        continue;
      }}
      flow.removeChild(node);
      finishPage();
      startPage();
      flow.appendChild(node);
      if (!fits() && block.type === 'heading') {{
        continue;
      }}
    }}
    if (block.type === 'heading' && flow.scrollHeight > content.clientHeight - 150) {{
      flow.removeChild(node);
      finishPage();
      startPage();
      flow.appendChild(node);
    }}
  }}
  finishPage();
}}
window.__ABM_CARDS_READY__ = true;
</script></body></html>"""


async def render_cards(document: CardDocument, *, no_sandbox: bool = False) -> list[bytes]:
    if document.style_id not in _ALLOWED_STYLES:
        document.style_id = "xhs-paper"
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ApiError(
            503,
            "ABM_CREATION_RENDER_UNAVAILABLE",
            "Card rendering needs the optional render extras (playwright).",
            retryable=False,
            action="contact_admin",
        ) from exc

    html = _card_html(document)
    async with _semaphore():
        try:
            async with async_playwright() as playwright:
                launch_args = []
                if no_sandbox:
                    launch_args.append("--no-sandbox")
                browser = await playwright.chromium.launch(headless=True, args=launch_args)
                try:
                    page = await browser.new_page(
                        viewport={"width": 1080, "height": 1440},
                        device_scale_factor=1,
                    )
                    await page.set_content(html, wait_until="load")
                    await page.wait_for_function(
                        "window.__ABM_CARDS_READY__ === true", timeout=15000
                    )
                    count = await page.locator(".card").count()
                    shots: list[bytes] = []
                    for index in range(count):
                        element = page.locator(".card").nth(index)
                        shots.append(await element.screenshot(type="png"))
                    return shots
                finally:
                    await browser.close()
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApiError(
                503,
                "ABM_CREATION_RENDER_UNAVAILABLE",
                f"Card rendering failed: {exc}",
                retryable=True,
                action="retry",
            ) from exc
