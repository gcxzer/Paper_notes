"""说明：选择和配置可用的 web_search provider。

作用：根据配置、凭据和开关决定使用 Brave、Tavily 或禁用搜索。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_config.ai_settings import resolve_brave_search_api_key, resolve_tavily_api_key
from app_config.secrets import LOCAL_STATE_DIR
from tools.web_search.brave import BraveWebSearch
from tools.web_search.common import search_error
from tools.web_search.tavily import TavilyWebSearch


CUSTOM_PROVIDER_PRIORITY = ("Tavily", "Brave")


class ConfiguredWebSearch:
    """Dispatch the model-visible web_search tool to the configured custom provider."""

    def __call__(
        self,
        *,
        query: str,
        limit: int = 5,
        allowed_domains: list[str] | None = None,
        recency_days: int | None = None,
        include_summary: bool = True,
    ) -> dict[str, Any]:
        provider_name = _configured_custom_provider()
        if provider_name == "Tavily":
            tavily_key = resolve_tavily_api_key().value
            if tavily_key:
                return TavilyWebSearch(api_key=tavily_key)(
                    query=query,
                    limit=limit,
                    allowed_domains=allowed_domains,
                    recency_days=recency_days,
                    include_summary=include_summary,
                )
        if provider_name == "Brave":
            brave_key = resolve_brave_search_api_key().value
            if brave_key:
                return BraveWebSearch(api_key=brave_key)(
                    query=query,
                    limit=limit,
                    allowed_domains=allowed_domains,
                    recency_days=recency_days,
                    include_summary=include_summary,
                )
        return search_error(
            f"Web Search requires {_key_name(provider_name)} when native web search is not used.",
            "web_search_provider_required",
            query=query,
        )


def configured_web_search_available() -> bool:
    provider_name = _configured_custom_provider()
    if provider_name == "Tavily":
        return resolve_tavily_api_key().configured
    if provider_name == "Brave":
        return resolve_brave_search_api_key().configured
    return False


def configured_web_search_provider_name() -> str:
    return _configured_custom_provider()


def _configured_custom_provider() -> str:
    path = LOCAL_STATE_DIR / "tool-settings.json"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return CUSTOM_PROVIDER_PRIORITY[0]
    toolsets = data.get("toolsets") if isinstance(data, dict) else {}
    web_search = toolsets.get("web_search") if isinstance(toolsets, dict) else {}
    custom = web_search.get("custom_provider", web_search.get("customProvider")) if isinstance(web_search, dict) else {}
    if not isinstance(custom, dict):
        return CUSTOM_PROVIDER_PRIORITY[0]
    for provider_name in CUSTOM_PROVIDER_PRIORITY:
        if _provider_enabled(custom, provider_name):
            return provider_name
    return CUSTOM_PROVIDER_PRIORITY[0]


def _provider_enabled(custom: dict[str, Any], name: str) -> bool:
    raw = custom.get(name, custom.get(name.lower()))
    return isinstance(raw, dict) and raw.get("enabled") is True


def _key_name(provider_name: str) -> str:
    if provider_name == "Brave":
        return "BRAVE_SEARCH_API_KEY"
    return "TAVILY_API_KEY"
