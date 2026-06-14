from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from tools.web_search.common import searched_at, search_error


class BraveWebSearch:
    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = "https://api.search.brave.com/res/v1/web/search",
        transport: Callable[[str, dict[str, str], str], dict[str, Any]] | None = None,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.transport = transport or get_brave_json

    def __call__(
        self,
        *,
        query: str,
        limit: int = 5,
        allowed_domains: list[str] | None = None,
        recency_days: int | None = None,
        include_summary: bool = True,
    ) -> dict[str, Any]:
        if not self.api_key.strip():
            return search_error(
                "Web Search requires BRAVE_SEARCH_API_KEY when Brave Search is selected.",
                "web_search_provider_required",
                query=query,
            )
        params: dict[str, str] = {
            "q": _query_with_domains(query, allowed_domains or []),
            "count": str(max(1, min(10, int(limit or 5)))),
            "search_lang": "en",
            "country": "us",
        }
        freshness = _freshness(recency_days)
        if freshness:
            params["freshness"] = freshness
        response = self.transport(self.endpoint, params, self.api_key)
        web = response.get("web") if isinstance(response, dict) else {}
        results = web.get("results") if isinstance(web, dict) else []
        sources: list[dict[str, str]] = []
        if isinstance(results, list):
            for item in results[:limit]:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                sources.append({
                    "title": str(item.get("title") or url).strip(),
                    "url": url,
                    "snippet": str(item.get("description") or item.get("snippet") or "").strip(),
                })
        return {
            "success": True,
            "query": query,
            "answer": _summary_from_sources(sources) if include_summary else "",
            "sources": sources,
            "citations": [],
            "searched_at": searched_at(),
            "provider": "brave",
            "error": "",
            "code": "",
        }


def get_brave_json(endpoint: str, params: dict[str, str], api_key: str) -> dict[str, Any]:
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Brave Search failed with HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Brave Search failed: {error.reason}") from error
    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        raise RuntimeError("Brave Search returned an invalid response.")
    return parsed


def _query_with_domains(query: str, domains: list[str]) -> str:
    cleaned = [domain.strip().removeprefix("https://").removeprefix("http://").strip("/") for domain in domains]
    cleaned = [domain for domain in cleaned if domain]
    if not cleaned:
        return query
    domain_query = " OR ".join(f"site:{domain}" for domain in cleaned)
    return f"({domain_query}) {query}"


def _freshness(recency_days: int | None) -> str:
    if not recency_days:
        return ""
    if recency_days <= 1:
        return "pd"
    if recency_days <= 7:
        return "pw"
    if recency_days <= 31:
        return "pm"
    if recency_days <= 365:
        return "py"
    return ""


def _summary_from_sources(sources: list[dict[str, str]]) -> str:
    snippets = [source["snippet"] for source in sources if source.get("snippet")]
    return " ".join(snippets[:2]).strip()
