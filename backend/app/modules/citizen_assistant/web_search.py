"""
Keyless web search (improvisation step).

After the PageIndex reasoning pass, if the knowledge base does not fully
cover the query we call the public web to improvise — no API key, no
billing. Uses DuckDuckGo's HTML endpoint and a tolerant parser; any
failure degrades to an empty result (the answer simply won't have web
context rather than erroring).
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any

import httpx

log = logging.getLogger("citadel.citizen_assistant.web_search")

_DDG_HTML = "https://html.duckduckgo.com/html/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.S,
)
_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(?P<snip>.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return html.unescape(_TAG_RE.sub("", s or "")).strip()


def search(query: str, max_results: int = 5, timeout: float = 12.0) -> list[dict[str, Any]]:
    """Return [{title, url, snippet}] — best effort, never raises."""
    if not query or not query.strip():
        return []
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": _UA}) as c:
            r = c.post(_DDG_HTML, data={"q": query.strip()})
            r.raise_for_status()
            body = r.text
    except Exception as e:
        log.info("web search failed (%s) — continuing without web context", e)
        return []

    titles = list(_RESULT_RE.finditer(body))
    snips = [_clean(m.group("snip")) for m in _SNIPPET_RE.finditer(body)]
    out: list[dict[str, Any]] = []
    for i, m in enumerate(titles[:max_results]):
        url = html.unescape(m.group("url"))
        # DDG wraps external links in a redirect; pull the real target
        rm = re.search(r"uddg=([^&]+)", url)
        if rm:
            import urllib.parse
            url = urllib.parse.unquote(rm.group(1))
        out.append({
            "title": _clean(m.group("title")),
            "url": url,
            "snippet": snips[i] if i < len(snips) else "",
        })
    return out


def as_context_block(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = ["PUBLIC WEB RESULTS (use only to improvise/verify; cite as web):"]
    for i, r in enumerate(results, 1):
        lines.append(f"[W{i}] {r['title']}\n{r['snippet']}\n({r['url']})")
    return "\n".join(lines)
