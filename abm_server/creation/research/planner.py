"""Query planning for creation research jobs.

The planner is deliberately rule based: an LLM expansion can be layered on top
later, but a job must always be able to start without one.
"""

from __future__ import annotations

from typing import Any

ENGINE_IDS = ("bing", "baidu", "duckduckgo", "google", "xiaohongshu")
DEPTH_PAGE_BUDGET = {"quick": 10, "standard": 30, "deep": 80}
DEPTH_LABELS = {"quick": "快速", "standard": "标准", "deep": "深度"}

_QUERY_SUFFIXES: tuple[tuple[str | None, float], ...] = (
    (None, 1.0),
    ("怎么做", 0.8),
    ("是什么", 0.7),
    ("推荐", 0.6),
    ("2026", 0.5),
)

MAX_KEYWORDS = 5
MAX_EXCLUSIONS = 10
MAX_QUERIES = 6
MIN_QUERIES = 2


def _clean_list(values: Any, limit: int) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        item = " ".join(value.split())
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item[:80])
        if len(cleaned) >= limit:
            break
    return cleaned


def normalize_engines(values: Any) -> list[str]:
    if not isinstance(values, list):
        return ["bing"]
    engines: list[str] = []
    for value in values:
        if isinstance(value, str) and value in ENGINE_IDS and value not in engines:
            engines.append(value)
    return engines or ["bing"]


def pages_for_depth(depth: str) -> int:
    return DEPTH_PAGE_BUDGET.get(depth, DEPTH_PAGE_BUDGET["standard"])


def build_plan(
    keywords: Any,
    exclusions: Any,
    engines: Any,
    depth: str = "standard",
) -> list[dict[str, Any]]:
    """Build a deterministic query plan from user keywords.

    Each entry describes one search query and the engines it runs on. The plan
    is stored on the job so the UI can show and replay it.
    """
    clean_keywords = _clean_list(keywords, MAX_KEYWORDS)
    if not clean_keywords:
        return []
    clean_exclusions = _clean_list(exclusions, MAX_EXCLUSIONS)
    engine_ids = normalize_engines(engines)
    suffix = " ".join(f"-{item}" for item in clean_exclusions)

    candidates: list[dict[str, Any]] = []
    for keyword in clean_keywords:
        for text, priority in _QUERY_SUFFIXES:
            query = keyword if text is None else f"{keyword} {text}"
            if suffix:
                query = f"{query} {suffix}"
            candidates.append({"query": query, "priority": priority})

    candidates.sort(key=lambda item: item["priority"], reverse=True)
    plan: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        query = item["query"]
        if query in seen:
            continue
        seen.add(query)
        plan.append(
            {
                "id": f"q{len(plan) + 1}",
                "query": query,
                "engines": list(engine_ids),
                "priority": item["priority"],
            }
        )
        if len(plan) >= MAX_QUERIES:
            break
    return plan if len(plan) >= MIN_QUERIES else plan


def plan_summary(plan: list[dict[str, Any]], depth: str) -> dict[str, Any]:
    engines = sorted({engine for item in plan for engine in item.get("engines", [])})
    return {
        "queries": len(plan),
        "engines": engines,
        "depth": depth,
        "pageBudget": pages_for_depth(depth),
        "searchPages": len(plan) * max(1, len(engines)),
    }


__all__ = [
    "DEPTH_LABELS",
    "DEPTH_PAGE_BUDGET",
    "ENGINE_IDS",
    "build_plan",
    "normalize_engines",
    "pages_for_depth",
    "plan_summary",
]
