from __future__ import annotations

import json

from abm_server.creation import compose


def _parse(text: str, platform: str = "master"):
    return compose.parse_draft(text, platform=platform, fallback_title="兜底标题")


def test_parses_fenced_json_with_missing_comma() -> None:
    text = """```json
{
  "title": "标题",
  "body": "第一段\\n\\n第二段"
  "tags": ["A", "B"],
  "outline": ["一", "二"]
}
```"""
    draft = _parse(text)
    assert draft.title == "标题"
    assert draft.body == "第一段\n\n第二段"
    assert draft.tags == ["A", "B"]
    assert draft.outline == ["一", "二"]


def test_parses_json_with_raw_newlines_and_trailing_comma() -> None:
    text = '{"title": "标题", "body": "第一行\n第二行", "tags": ["x",]}'
    draft = _parse(text)
    assert draft.body == "第一行\n第二行"
    assert draft.tags == ["x"]


def test_parses_chinese_keys_and_nested_wrapper() -> None:
    chinese = json.dumps(
        {"标题": "中文标题", "正文": "中文正文", "标签": ["a"], "提纲": ["一"]},
        ensure_ascii=False,
    )
    draft = _parse(chinese)
    assert draft.title == "中文标题"
    assert draft.body == "中文正文"
    assert draft.tags == ["a"]

    nested = _parse('{"data": {"title": "嵌套标题", "body": "嵌套正文"}}')
    assert nested.title == "嵌套标题"
    assert nested.body == "嵌套正文"


def test_parses_json_wrapped_in_prose() -> None:
    text = '分析如下：\n```json\n{"title": "T", "body": "B"}\n```\n以上。'
    draft = _parse(text)
    assert draft.title == "T"
    assert draft.body == "B"


def test_body_list_and_outline_string_are_normalised() -> None:
    text = json.dumps(
        {"title": "T", "body": ["第一段", "第二段"], "outline": "1. 一\n2. 二"},
        ensure_ascii=False,
    )
    draft = _parse(text)
    assert draft.body == "第一段\n\n第二段"
    assert draft.outline == ["一", "二"]


def test_malformed_json_never_becomes_the_body() -> None:
    text = '  "title": "x",\n  "body": "y"'
    assert compose.is_json_like(text)
    draft = _parse(text)
    assert draft.body == ""
    assert draft.title == "兜底标题"


def test_single_brace_is_not_used_as_title() -> None:
    text = '{\n  "title": "x",\n  "body": "y"'
    draft = _parse(text)
    assert draft.title == "兜底标题"
    assert draft.body == ""


def test_plain_markdown_still_works() -> None:
    draft = _parse("# 手写标题\n\n第一段\n第二段")
    assert draft.title == "手写标题"
    assert draft.body.startswith("第一段")


def test_plain_text_without_heading_uses_first_line() -> None:
    text = "今天是晴天\n\n适合出门走走"
    draft = _parse(text)
    assert draft.title == "今天是晴天"
    assert draft.body.startswith("适合出门走走")
