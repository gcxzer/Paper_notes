from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool

from tools.web_search.common import safe_limit, safe_optional_int, search_error, text_list
from tools.web_search.providers import ConfiguredWebSearch


WEB_SEARCH_TOOL_NAME = "web_search"
WEB_SEARCH_TOOLSET = "web_search"
WebSearchProvider = Callable[..., dict[str, Any]]


def create_tools(*, search_provider: WebSearchProvider | None = None) -> list[StructuredTool]:
    return [
        StructuredTool(
            name=WEB_SEARCH_TOOL_NAME,
            description=(
                "Search the public web using the configured Web Search provider. Use this for current facts, "
                "external sources, citations, and information outside the local Paper Notes library. "
                "If a specific URL must be read, use web_fetch instead."
            ),
            args_schema=web_search_parameters(),
            func=lambda **kwargs: web_search(dict(kwargs), search_provider=search_provider),
        )
    ]


def web_search_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 5,
                "description": "Maximum number of sources to return.",
            },
            "allowed_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional domains to prefer or restrict the search to.",
            },
            "recency_days": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional recency window in days.",
            },
            "include_summary": {
                "type": "boolean",
                "default": True,
                "description": "Whether to include a short synthesized answer.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }


def web_search(
    args: dict[str, Any],
    *,
    search_provider: WebSearchProvider | None = None,
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return search_error("query is required.", "invalid_query", query=query)
    limit = safe_limit(args.get("limit"), default=5, maximum=10)
    allowed_domains = text_list(args.get("allowed_domains"))
    recency_days = safe_optional_int(args.get("recency_days"))
    include_summary = args.get("include_summary", True) is not False
    provider = search_provider or ConfiguredWebSearch()
    try:
        return provider(
            query=query,
            limit=limit,
            allowed_domains=allowed_domains,
            recency_days=recency_days,
            include_summary=include_summary,
        )
    except Exception as error:
        return search_error(str(error) or "Web Search failed.", "web_search_failed", query=query)
