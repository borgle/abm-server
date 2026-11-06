"""Markdown -> block list -> platform layouts.

The studio preview renders Markdown in the browser, but exports must be
byte-stable and testable, so they are produced on the server. The parser keeps
raw HTML disabled: only Markdown syntax is rendered, which is what WeChat and
the card renderer can safely style.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt

_INLINE_STYLES = {
    "h2": "font-size:22px;line-height:1.5;font-weight:700;margin:28px 0 12px;color:#10110f;",
    "h3": "font-size:18px;line-height:1.6;font-weight:700;margin:22px 0 10px;color:#10110f;",
    "p": "font-size:16px;line-height:1.85;margin:0 0 16px;color:#2b2d27;letter-spacing:.01em;",
    "ul": "margin:0 0 16px;padding-left:22px;",
    "ol": "margin:0 0 16px;padding-left:22px;",
    "li": "font-size:16px;line-height:1.85;margin:0 0 8px;color:#2b2d27;",
    "blockquote": (
        "margin:0 0 18px;padding:12px 16px;border-left:3px solid #10110f;"
        "background:#f4f4ed;color:#4a4d43;font-size:15px;line-height:1.8;"
    ),
    "pre": (
        "margin:0 0 18px;padding:14px 16px;background:#10110f;color:#e8eae0;"
        "border-radius:10px;font-size:13px;line-height:1.7;overflow-x:auto;"
    ),
    "code": "font-family:Menlo,Consolas,monospace;",
    "table": "width:100%;border-collapse:collapse;margin:0 0 18px;font-size:14px;",
    "th": (
        "border:1px solid #d9dbd0;padding:8px 10px;background:#f4f4ed;"
        "text-align:left;font-weight:700;color:#10110f;"
    ),
    "td": "border:1px solid #d9dbd0;padding:8px 10px;color:#2b2d27;",
    "figcaption": "font-size:13px;color:#7a7d71;margin:6px 0 18px;text-align:center;",
}

_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_IMG_ATTR = re.compile(r'(src|alt)="([^"]*)"', re.IGNORECASE)
_LINK_TAG = re.compile(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


@dataclass(slots=True)
class Block:
    type: str
    html: str = ""
    level: int = 0
    ordered: bool = False
    index: int = 0
    text: str = ""
    lang: str = ""
    src: str = ""
    alt: str = ""
    first: bool = True
    last: bool = True
    meta: dict = field(default_factory=dict)


def _renderer() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    md.enable("table")
    return md


def _render_inline(md: MarkdownIt, token) -> str:  # noqa: ANN001 - markdown-it token
    return md.renderer.render([token], md.options, {})


def parse_blocks(markdown: str) -> list[Block]:
    md = _renderer()
    tokens = md.parse(markdown or "")
    blocks: list[Block] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        kind = token.type

        if kind == "heading_open":
            level = int(token.tag[1:]) if token.tag[1:].isdigit() else 2
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            blocks.append(
                Block(
                    type="heading",
                    html=_render_inline(md, inline) if inline is not None else "",
                    level=level,
                )
            )
            index += 3
            continue

        if kind == "paragraph_open":
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            if inline is not None and inline.type == "inline":
                images = [child for child in inline.children or [] if child.type == "image"]
                if images and len(images) == len(inline.children or []):
                    for child in images:
                        blocks.append(
                            Block(
                                type="image",
                                src=str(child.attrs.get("src") or ""),
                                alt=str(child.content or ""),
                            )
                        )
                    index += 3
                    continue
                blocks.append(Block(type="paragraph", html=_render_inline(md, inline)))
                index += 3
                continue

        if kind in {"bullet_list_open", "ordered_list_open"}:
            ordered = kind == "ordered_list_open"
            depth = token.level
            index += 1
            item_no = 0
            items: list[Block] = []
            while index < len(tokens):
                current = tokens[index]
                if (
                    current.type in {"bullet_list_open", "ordered_list_open"}
                    and current.level == depth + 1
                ):
                    index += 1
                    continue
                if (
                    current.type in {"bullet_list_close", "ordered_list_close"}
                    and current.level == depth
                ):
                    index += 1
                    break
                if current.type == "list_item_open":
                    item_no += 1
                    item_tokens = []
                    cursor = index + 1
                    while cursor < len(tokens):
                        candidate = tokens[cursor]
                        if candidate.type == "list_item_close" and candidate.level == current.level:
                            break
                        item_tokens.append(candidate)
                        cursor += 1
                    inner = md.renderer.render(item_tokens, md.options, {})
                    items.append(
                        Block(
                            type="list_item",
                            html=inner,
                            ordered=ordered,
                            index=item_no,
                        )
                    )
                    index = cursor + 1
                    continue
                index += 1
            if items:
                items[0].first = True
                items[-1].last = True
                blocks.extend(items)
            continue

        if kind == "blockquote_open":
            depth = token.level
            index += 1
            inner_start = index
            while index < len(tokens):
                current = tokens[index]
                if current.type == "blockquote_close" and current.level == depth:
                    break
                index += 1
            inner = md.renderer.render(tokens[inner_start:index], md.options, {})
            blocks.append(Block(type="quote", html=inner))
            index += 1
            continue

        if kind in {"fence", "code_block"}:
            blocks.append(
                Block(
                    type="code",
                    text=token.content.rstrip("\n"),
                    lang=str(token.info or "").split()[0] if token.info else "",
                )
            )
            index += 1
            continue

        if kind == "hr":
            blocks.append(Block(type="hr"))
            index += 1
            continue

        if kind == "table_open":
            depth = token.level
            start = index
            index += 1
            while index < len(tokens):
                current = tokens[index]
                if current.type == "table_close" and current.level == depth:
                    index += 1
                    break
                index += 1
            blocks.append(
                Block(type="table", html=md.renderer.render(tokens[start:index], md.options, {}))
            )
            continue

        index += 1
    return blocks


def _rewrite_html(
    fragment: str,
    images: list[dict[str, str]],
    *,
    image_base: str = "",
) -> str:
    def replace_image(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = {key.lower(): value for key, value in _IMG_ATTR.findall(tag)}
        src = attrs.get("src", "")
        alt = attrs.get("alt", "")
        number = len(images) + 1
        images.append({"index": number, "src": src, "alt": alt})
        label = html_module.escape(alt or f"图 {number}")
        return (
            f'<div style="margin:0 0 18px;padding:18px;border:1px dashed #c9ccbf;'
            f"border-radius:10px;background:#f7f7f1;color:#7a7d71;font-size:14px;"
            f'text-align:center;">[图 {number}] {label}'
            f'<br><span style="font-size:12px;">上传压缩包里的 image-{number:02d}</span></div>'
        )

    def replace_link(match: re.Match[str]) -> str:
        url = match.group(1)
        text = match.group(2)
        escaped = html_module.escape(url)
        return f'{text}<span style="color:#7a7d71;font-size:13px;">（{escaped}）</span>'

    fragment = _IMG_TAG.sub(replace_image, fragment)
    fragment = _LINK_TAG.sub(replace_link, fragment)
    return fragment


def _style_table(fragment: str) -> str:
    fragment = re.sub(r"<table>", f'<table style="{_INLINE_STYLES["table"]}">', fragment)
    fragment = re.sub(r"<th>", f'<th style="{_INLINE_STYLES["th"]}">', fragment)
    fragment = re.sub(r"<td>", f'<td style="{_INLINE_STYLES["td"]}">', fragment)
    return fragment


def _block_html(block: Block) -> str:
    if block.type == "heading":
        tag = f"h{min(max(block.level, 2), 3)}"
        style = _INLINE_STYLES.get(tag, _INLINE_STYLES["h2"])
        return f'<{tag} style="{style}">{block.html}</{tag}>'
    if block.type == "paragraph":
        return f'<p style="{_INLINE_STYLES["p"]}">{block.html}</p>'
    if block.type == "list_item":
        content = block.html.strip()
        if content.startswith("<p>") and content.endswith("</p>") and content.count("<p>") == 1:
            content = content[3:-4]
        content = content.replace("<p>", f'<p style="{_INLINE_STYLES["p"]}">')
        content = content.replace("<ul>", f'<ul style="{_INLINE_STYLES["ul"]}">')
        content = content.replace("<ol>", f'<ol style="{_INLINE_STYLES["ol"]}">')
        marker = f"{block.index}. " if block.ordered else "• "
        return (
            f'<div style="display:flex;gap:8px;font-size:16px;line-height:1.85;'
            f'margin:0 0 8px;color:#2b2d27;"><span>{html_module.escape(marker)}</span>'
            f'<div style="flex:1;min-width:0;">{content}</div></div>'
        )
    if block.type == "quote":
        return f'<blockquote style="{_INLINE_STYLES["blockquote"]}">{block.html}</blockquote>'
    if block.type == "code":
        return (
            f'<pre style="{_INLINE_STYLES["pre"]}"><code style="{_INLINE_STYLES["code"]}">'
            f"{html_module.escape(block.text)}</code></pre>"
        )
    if block.type == "hr":
        return '<hr style="border:0;border-top:1px solid #d9dbd0;margin:24px 0;" />'
    if block.type == "table":
        return _style_table(block.html)
    if block.type == "image":
        return (
            f'<img src="{html_module.escape(block.src)}" '
            f'alt="{html_module.escape(block.alt or "")}" />'
        )
    return ""


def render_wechat(title: str, blocks: list[Block]) -> tuple[str, list[dict[str, str]]]:
    images: list[dict[str, str]] = []
    body_parts = [
        f'<h1 style="font-size:24px;line-height:1.45;font-weight:800;margin:0 0 20px;'
        f'color:#10110f;">{html_module.escape(title)}</h1>'
    ]
    for block in blocks:
        fragment = _block_html(block)
        body_parts.append(_rewrite_html(fragment, images))
    body = "\n".join(part for part in body_parts if part)
    document = (
        '<!doctype html><html lang="zh"><head><meta charset="utf-8" />'
        f"<title>{html_module.escape(title)}</title></head>"
        '<body style="margin:0;padding:0;background:#ffffff;">'
        '<div style="max-width:677px;margin:0 auto;padding:22px 18px 40px;'
        "font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',"
        "'Microsoft YaHei',sans-serif;\">"
        f"{body}</div></body></html>"
    )
    return document, images
