from __future__ import annotations

from abm_server.creation.layout import parse_blocks, render_wechat

MARKDOWN = """# 标题

第一段，带 **加粗** 和 [外链](https://example.com)。

- 条目一
- 条目二

![图](https://example.com/cover.png)
"""


def test_parse_blocks_keeps_structure() -> None:
    types = [block.type for block in parse_blocks(MARKDOWN)]
    assert "heading" in types
    assert "paragraph" in types
    assert types.count("list_item") == 2
    assert "image" in types


def test_wechat_export_is_inline_and_has_image_hint() -> None:
    html, images = render_wechat("标题", parse_blocks(MARKDOWN))
    assert "<style" not in html
    assert "class=" not in html
    assert "style=" in html
    assert "[图 1]" in html
    assert "上传压缩包里的 image-01" in html
    assert len(images) == 1
