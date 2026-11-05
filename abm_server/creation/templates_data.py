"""Static workflow templates for the creation workspace.

Templates stay in code for the first release. They describe steps and a single
prefill action so the UI can open the right page without creating anything on
its own.
"""

from __future__ import annotations

from typing import Any

CATEGORIES = [
    {"id": "research", "name": "检索", "description": "从关键词到可用来源。"},
    {"id": "compose", "name": "创作", "description": "从主稿到平台变体。"},
    {"id": "publish", "name": "发布", "description": "发布前检查与填充。"},
    {"id": "assets", "name": "资产维护", "description": "整理素材与历史版本。"},
]

TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "research-competitor",
        "category": "research",
        "name": "竞品资料检索",
        "description": "四个搜索引擎并行检索，保留可引用的公开来源。",
        "platforms": ["master"],
        "steps": ["填写关键词", "四个引擎检索", "筛选来源", "加入素材库"],
        "inputs": ["keywords"],
        "action": {
            "kind": "radar",
            "keywords": ["竞品分析"],
            "engines": ["bing", "baidu", "duckduckgo", "google"],
            "depth": "standard",
        },
    },
    {
        "id": "research-xhs-topic",
        "category": "research",
        "name": "小红书选题调研",
        "description": "用已登录浏览器检索小红书笔记，观察标题与互动结构。",
        "platforms": ["xiaohongshu"],
        "steps": ["确认登录状态", "检索笔记", "记录标题与互动", "生成选题"],
        "inputs": ["keywords"],
        "action": {
            "kind": "radar",
            "keywords": ["小户型收纳"],
            "engines": ["xiaohongshu"],
            "depth": "quick",
        },
    },
    {
        "id": "compose-xhs-rewrite",
        "category": "compose",
        "name": "小红书选题改写",
        "description": "把主稿改写成一条小红书笔记，标题控制在 20 字内。",
        "platforms": ["xiaohongshu"],
        "steps": ["选择主稿", "生成 3 个标题", "压缩正文", "补 5–10 个标签"],
        "inputs": ["asset"],
        "action": {
            "kind": "asset",
            "title": "小红书笔记：未命名选题",
            "platform": "xiaohongshu",
        },
    },
    {
        "id": "compose-video-script",
        "category": "compose",
        "name": "长文转视频口播",
        "description": "把一篇长文压缩成 60–90 秒口播稿，并给分镜建议。",
        "platforms": ["shipinhao"],
        "steps": ["提取主稿", "压缩到 2 分钟", "拆分镜头", "录制准备"],
        "inputs": ["asset"],
        "action": {
            "kind": "asset",
            "title": "视频口播：未命名脚本",
            "platform": "shipinhao",
        },
    },
    {
        "id": "publish-check",
        "category": "publish",
        "name": "发布前检查",
        "description": "按平台检查标题、字数、标签、引用与合规风险。",
        "platforms": ["xiaohongshu", "wechat", "zhihu", "shipinhao"],
        "steps": ["选择资产", "平台约束检查", "引用核对", "发布清单"],
        "inputs": ["asset"],
        "action": {"kind": "assets"},
    },
    {
        "id": "assets-dedupe",
        "category": "assets",
        "name": "素材去重与合并",
        "description": "按规范 URL 与内容指纹清理重复来源。",
        "platforms": ["master"],
        "steps": ["打开素材库", "按域名筛选", "比较指纹", "删除重复"],
        "inputs": ["sources"],
        "action": {"kind": "library"},
    },
]


def template_list() -> list[dict[str, Any]]:
    return [dict(item) for item in TEMPLATES]


__all__ = ["CATEGORIES", "TEMPLATES", "template_list"]
