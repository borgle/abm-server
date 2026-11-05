"""Browser adapters for creation research.

Every adapter is a pair of declarative search settings plus a JavaScript body
that runs through ``browser_inject_script``. The scripts only read public page
content; they never submit forms, click consent dialogs, or touch cookies.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SEARCH_ENGINES: dict[str, dict[str, Any]] = {
    "bing": {
        "id": "bing",
        "label": "必应",
        "base": "https://www.bing.com/search",
        "queryParam": "q",
        "offsetParam": "first",
        "offsetStep": 10,
        "selectors": ["li.b_algo", "#b_results > li.b_algo"],
        "rateSeconds": 2.0,
        "loginRequired": False,
        "kind": "article",
    },
    "baidu": {
        "id": "baidu",
        "label": "百度",
        "base": "https://www.baidu.com/s",
        "queryParam": "wd",
        "offsetParam": "pn",
        "offsetStep": 10,
        "selectors": ["div.result", "div.c-container", "#content_left > div"],
        "rateSeconds": 2.0,
        "loginRequired": False,
        "kind": "article",
    },
    "duckduckgo": {
        "id": "duckduckgo",
        "label": "DuckDuckGo",
        "base": "https://html.duckduckgo.com/html/",
        "queryParam": "q",
        "offsetParam": None,
        "offsetStep": 0,
        "selectors": [".result", ".web-result"],
        "rateSeconds": 3.0,
        "loginRequired": False,
        "kind": "article",
    },
    "google": {
        "id": "google",
        "label": "Google",
        "base": "https://www.google.com/search",
        "queryParam": "q",
        "offsetParam": "start",
        "offsetStep": 10,
        "selectors": ["div.g", "div.MjjYud", "div[data-hveid]"],
        "rateSeconds": 3.0,
        "loginRequired": False,
        "kind": "article",
    },
    "xiaohongshu": {
        "id": "xiaohongshu",
        "label": "小红书",
        "base": "https://www.xiaohongshu.com/search_result",
        "queryParam": "keyword",
        "offsetParam": None,
        "offsetStep": 0,
        "selectors": ["section.note-item", "div.note-item", "a.cover"],
        "rateSeconds": 3.0,
        "loginRequired": True,
        "kind": "note",
    },
}

_ATTENTION_JS = """
function detectAttention() {
  var text = ((document.body && document.body.innerText) || '').slice(0, 5000);
  var href = String(location.href || '');
  if (/\\/sorry\\/|captcha|unusual traffic/i.test(href)
      || /验证码|安全验证|人机验证|captcha|unusual traffic/i.test(text)) {
    return { reason: 'captcha', message: 'The site requires a verification step.' };
  }
  var password = document.querySelector('input[type="password"]');
  if (password && /登录|sign in|log in|扫码/i.test(text)) {
    return { reason: 'login_required', message: 'The site requires a signed-in browser.' };
  }
  if (/google\\./i.test(location.hostname)
      && /before you continue|consent|同意|接受所有/i.test(text)) {
    return { reason: 'consent_required', message: 'Google is showing a consent screen.' };
  }
  return null;
}
"""

SEARCH_SCRIPT = (
    _ATTENTION_JS
    + """
var limit = Number(args.limit || 10);
var selectors = Array.isArray(args.selectors) ? args.selectors : [];
var seen = {};
var results = [];
for (var s = 0; s < selectors.length; s += 1) {
  var nodes = [];
  try { nodes = Array.prototype.slice.call(document.querySelectorAll(selectors[s])); }
  catch (error) { continue; }
  for (var i = 0; i < nodes.length; i += 1) {
    var node = nodes[i];
    var anchor = node.querySelector('h2 a[href], h3 a[href]') || node.querySelector('a[href]');
    if (!anchor) continue;
    var href = anchor.href || '';
    if (!/^https?:/i.test(href) || seen[href]) continue;
    seen[href] = true;
    var title = (anchor.innerText || anchor.textContent || '').trim();
    var text = (node.innerText || node.textContent || '').trim();
    var snippet = text.indexOf(title) === 0 ? text.slice(title.length) : text;
    results.push({
      title: title.slice(0, 300),
      url: href,
      snippet: snippet.replace(/\\s+/g, ' ').trim().slice(0, 320)
    });
    if (results.length >= limit) break;
  }
  if (results.length >= limit) break;
}
if (!results.length) {
  var headings = document.querySelectorAll('h2 a[href], h3 a[href]');
  for (var h = 0; h < headings.length; h += 1) {
    var link = headings[h];
    var target = link.href || '';
    if (!/^https?:/i.test(target) || seen[target]) continue;
    var text = (link.innerText || link.textContent || '').trim();
    if (text.length < 6) continue;
    seen[target] = true;
    results.push({ title: text.slice(0, 300), url: target, snippet: '' });
    if (results.length >= limit) break;
  }
}
return {
  url: location.href,
  title: document.title || '',
  results: results,
  needsAttention: detectAttention()
};
"""
)

ARTICLE_SCRIPT = (
    _ATTENTION_JS
    + """
var maxLength = Number(args.maxLength || 20000);
var selectors = ['article', 'main', '[role="main"]', '#js_content',
  '.rich_media_content', '.article-content', '.post-content', '.note-content',
  '.article', '.content'];
var best = '';
for (var s = 0; s < selectors.length; s += 1) {
  var nodes = [];
  try { nodes = Array.prototype.slice.call(document.querySelectorAll(selectors[s])); }
  catch (error) { continue; }
  for (var i = 0; i < nodes.length; i += 1) {
    var value = (nodes[i].innerText || '').trim();
    if (value.length > best.length) best = value;
  }
}
if (!best && document.body) {
  var clone = document.body.cloneNode(true);
  var drop = clone.querySelectorAll('nav,footer,aside,script,style,noscript,form,iframe');
  for (var d = 0; d < drop.length; d += 1) drop[d].remove();
  best = (clone.innerText || '').trim();
}
function meta(name) {
  var el = document.querySelector('meta[name="' + name + '"]')
    || document.querySelector('meta[property="' + name + '"]');
  return el ? (el.getAttribute('content') || '') : '';
}
var canonicalEl = document.querySelector('link[rel="canonical"]');
var timeEl = document.querySelector('time[datetime]');
return {
  url: location.href,
  title: (meta('og:title') || document.title || '').trim(),
  canonical: canonicalEl ? canonicalEl.href : '',
  author: meta('author') || meta('article:author') || '',
  published: meta('article:published_time')
    || (timeEl ? timeEl.getAttribute('datetime') : '') || '',
  language: document.documentElement.lang || '',
  text: best.slice(0, maxLength),
  needsAttention: detectAttention()
};
"""
)

XHS_NOTE_SCRIPT = (
    _ATTENTION_JS
    + """
var maxLength = Number(args.maxLength || 8000);
function pick(selectors) {
  for (var s = 0; s < selectors.length; s += 1) {
    var node = document.querySelector(selectors[s]);
    if (node) return (node.innerText || node.textContent || '').trim();
  }
  return '';
}
var title = pick(['#detail-title', '.note-content .title', '.title']);
var body = pick(['#detail-desc', '.note-content .desc', '.desc', '.note-text']);
if (!body) body = (document.body ? document.body.innerText : '').trim().slice(0, maxLength);
var tags = [];
var tagNodes = document.querySelectorAll('#detail-desc .tag, .note-content .tag');
for (var t = 0; t < tagNodes.length; t += 1) {
  var tag = (tagNodes[t].innerText || '').trim();
  if (tag && tags.indexOf(tag) < 0) tags.push(tag);
}
var author = pick(['.author-wrapper .username', '.username', '.author-name']);
var metrics = {};
var like = pick(['.like-wrapper .count', '.like-wrapper']);
var collect = pick(['.collect-wrapper .count', '.collect-wrapper']);
var comment = pick(['.comment-wrapper .count', '.comment-wrapper']);
if (like) metrics.likes = like;
if (collect) metrics.collects = collect;
if (comment) metrics.comments = comment;
return {
  url: location.href,
  title: title || document.title || '',
  canonical: location.href,
  author: author,
  published: '',
  language: 'zh',
  text: (title ? title + '\\n' : '') + body.slice(0, maxLength),
  tags: tags.slice(0, 20),
  metrics: metrics,
  needsAttention: detectAttention()
};
"""
)


def _decode_base64url(value: str) -> str:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8", "ignore")
    except (ValueError, binascii.Error):
        return ""
    return decoded if decoded.startswith("http") else ""


_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "fbclid",
    "gclid",
    "ref",
    "source",
    "from",
}

_MEDIA_DOMAINS = {
    "people.com.cn",
    "xinhuanet.com",
    "news.cn",
    "thepaper.cn",
    "caixin.com",
    "36kr.com",
    "huxiu.com",
    "sspai.com",
    "ifanr.com",
    "zhihu.com",
    "wikipedia.org",
    "medium.com",
}

_PERSONAL_DOMAINS = {"blogspot.com", "wordpress.com", "github.io", "substack.com"}


def search_url(engine_id: str, query: str, page: int = 0) -> str:
    engine = SEARCH_ENGINES[engine_id]
    params: dict[str, str] = {engine["queryParam"]: query}
    if engine["offsetParam"] and page:
        params[engine["offsetParam"]] = str(page * engine["offsetStep"])
    return f"{engine['base']}?{urlencode(params)}"


_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def normalize_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw or " " in raw:
        return ""
    if "duckduckgo.com/l/" in raw:
        query = parse_qsl(urlsplit(raw).query)
        target = next((item for key, item in query if key == "uddg"), "")
        if target:
            raw = target
    parts_for_redirect = urlsplit(raw)
    redirect_host = (parts_for_redirect.hostname or "").lower()
    if redirect_host.endswith("bing.com") and parts_for_redirect.path == "/ck/a":
        query = dict(parse_qsl(parts_for_redirect.query))
        encoded = query.get("u", "")
        if encoded.startswith("a1"):
            decoded = _decode_base64url(encoded[2:])
            if decoded:
                raw = decoded
    elif redirect_host.endswith("google.com") and parts_for_redirect.path == "/url":
        query = dict(parse_qsl(parts_for_redirect.query))
        if query.get("q", "").startswith("http"):
            raw = query["q"]
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    host = parts.hostname.lower().removeprefix("www.")
    if not _HOST_RE.match(host) or ("." not in host and host != "localhost"):
        return ""
    netloc = host
    if parts.port and not (
        (parts.scheme == "http" and parts.port == 80)
        or (parts.scheme == "https" and parts.port == 443)
    ):
        netloc = f"{host}:{parts.port}"
    pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if key.lower() not in _TRACKING_PARAMS and not key.lower().startswith("utm_")
    ]
    query = urlencode(sorted(pairs))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", netloc, path, query, ""))


def domain_of(value: str) -> str:
    host = urlsplit(normalize_url(value)).hostname or ""
    return host


def normalize_title(value: str) -> str:
    return " ".join((value or "").split())[:500]


def excerpt_of(text: str, limit: int = 220) -> str:
    clean = " ".join((text or "").split())
    return clean[:limit]


def parse_tool_result(payload: Any) -> Any:
    """Read a browser tool payload from the extension envelope."""
    if not isinstance(payload, dict):
        return payload
    for key in ("structuredContent", "structured_content", "result"):
        value = payload.get(key)
        if value is not None:
            return value
    content = payload.get("content")
    if isinstance(content, list):
        texts = [
            item.get("text")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        for text in texts:
            try:
                return json.loads(text)
            except ValueError:
                continue
        return texts[0] if texts else None
    return payload


def attention_from(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("needsAttention")
    if isinstance(value, dict) and value.get("reason"):
        return {"reason": str(value["reason"]), "message": str(value.get("message") or "")}
    return None


def search_results(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    data = parse_tool_result(payload)
    if not isinstance(data, dict):
        return [], None
    items: list[dict[str, Any]] = []
    for raw in data.get("results") or []:
        if not isinstance(raw, dict):
            continue
        url = normalize_url(str(raw.get("url") or ""))
        title = normalize_title(str(raw.get("title") or ""))
        if not url or not title:
            continue
        items.append(
            {
                "url": url,
                "title": title,
                "snippet": str(raw.get("snippet") or "")[:320],
            }
        )
    return items, attention_from(data)


def article_payload(payload: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    data = parse_tool_result(payload)
    if not isinstance(data, dict):
        return None, None
    text = str(data.get("text") or "").strip()
    title = normalize_title(str(data.get("title") or ""))
    if not text:
        return None, attention_from(data)
    return (
        {
            "url": normalize_url(str(data.get("url") or "")),
            "canonical": normalize_url(str(data.get("canonical") or "")),
            "title": title,
            "author": str(data.get("author") or "").strip()[:255] or None,
            "published": str(data.get("published") or "").strip()[:64] or None,
            "language": str(data.get("language") or "").strip()[:16],
            "text": text,
            "tags": [str(tag)[:40] for tag in data.get("tags") or [] if str(tag).strip()][:20],
            "metrics": data.get("metrics") if isinstance(data.get("metrics"), dict) else {},
        },
        attention_from(data),
    )


def fingerprint_text(text: str) -> str:
    """64-bit SimHash over character trigrams, hex encoded."""
    clean = re.sub(r"\s+", " ", (text or "").lower())
    if len(clean) < 3:
        return ""
    weights = [0] * 64
    for index in range(len(clean) - 2):
        gram = clean[index : index + 3]
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            weights[bit] += 1 if value & (1 << bit) else -1
    result = 0
    for bit in range(64):
        if weights[bit] > 0:
            result |= 1 << bit
    return f"{result:016x}"


def hamming(left: str, right: str) -> int:
    if not left or not right:
        return 64
    return (int(left, 16) ^ int(right, 16)).bit_count()


def is_duplicate(left: str, right: str, threshold: int = 3) -> bool:
    return hamming(left, right) <= threshold


def _published_year(published: str | None) -> int | None:
    if not published:
        return None
    match = re.search(r"(19|20)\d{2}", published)
    return int(match.group(0)) if match else None


def score_credibility(
    *,
    url: str,
    author: str | None,
    published: str | None,
    text: str,
) -> tuple[int, dict[str, Any]]:
    domain = domain_of(url)
    if domain == "gov.cn" or domain.endswith((".gov", ".gov.cn", ".edu", ".edu.cn", ".ac.uk")):
        tier = 1.0
    elif any(domain == item or domain.endswith("." + item) for item in _MEDIA_DOMAINS):
        tier = 0.8
    elif any(domain == item or domain.endswith("." + item) for item in _PERSONAL_DOMAINS):
        tier = 0.35
    else:
        tier = 0.55 if domain else 0.3

    year = _published_year(published)
    if year is None:
        freshness = 0.5
    else:
        age = datetime.now(UTC).year - year
        freshness = 1.0 if age <= 1 else 0.7 if age <= 3 else 0.4

    references = min(1.0, text.count("http") / 5.0)
    length = len(text)
    completeness = (
        1.0 if length >= 2000 else 0.8 if length >= 800 else 0.5 if length >= 200 else 0.2
    )
    author_score = 1.0 if author else 0.4

    factors = {
        "domain": round(tier * 30),
        "author": round(author_score * 15),
        "freshness": round(freshness * 15),
        "references": round(references * 20),
        "completeness": round(completeness * 20),
    }
    return min(100, sum(factors.values())), factors


__all__ = [
    "ARTICLE_SCRIPT",
    "SEARCH_ENGINES",
    "SEARCH_SCRIPT",
    "XHS_NOTE_SCRIPT",
    "article_payload",
    "attention_from",
    "domain_of",
    "excerpt_of",
    "fingerprint_text",
    "hamming",
    "is_duplicate",
    "normalize_title",
    "normalize_url",
    "parse_tool_result",
    "score_credibility",
    "search_results",
    "search_url",
]
