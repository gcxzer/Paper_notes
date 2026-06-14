from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from tools.web_search.common import searched_at, search_error


class TavilyWebSearch:
    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = "https://api.tavily.com/search",
        transport: Callable[[str, dict[str, Any], str], dict[str, Any]] | None = None,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.transport = transport or post_tavily_json

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
                "Web Search requires TAVILY_API_KEY when Tavily is selected.",
                "web_search_provider_required",
                query=query,
            )
        payload: dict[str, Any] = {
            "query": query,
            "max_results": limit,
            "include_answer": include_summary,
            "include_raw_content": False,
        }
        if allowed_domains:
            payload["include_domains"] = allowed_domains
        if recency_days:
            payload["days"] = recency_days
        response = self.transport(self.endpoint, payload, self.api_key)
        results = response.get("results") if isinstance(response, dict) else []
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
                    "snippet": str(item.get("content") or item.get("snippet") or "").strip(),
                })
        return {
            "success": True,
            "query": query,
            "answer": str(response.get("answer") or "").strip() if include_summary and isinstance(response, dict) else "",
            "sources": sources,
            "citations": [],
            "searched_at": searched_at(),
            "provider": "tavily",
            "error": "",
            "code": "",
        }


def post_tavily_json(endpoint: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Tavily search failed with HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Tavily search failed: {error.reason}") from error
    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        raise RuntimeError("Tavily search returned an invalid response.")
    return parsed
