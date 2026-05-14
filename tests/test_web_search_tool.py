from __future__ import annotations

from tools.registry import ToolRegistry
import json

import tools.web_search.providers as web_search_providers
from tools.web_fetch import register_web_fetch_tool
from tools.web_search import BraveWebSearch, ConfiguredWebSearch, TavilyWebSearch, register_web_search_tool, web_search


def test_web_search_uses_injected_provider():
    def provider(**kwargs):
        return {
            "success": True,
            "query": kwargs["query"],
            "answer": "Answer",
            "sources": [{"title": "Source", "url": "https://example.com", "snippet": "Snippet"}],
            "citations": [],
            "searched_at": "2026-05-13T00:00:00+00:00",
            "provider": "test",
        }

    result = web_search(
        {
            "query": "Paper Notes",
            "limit": 50,
            "allowed_domains": ["example.com", "example.com"],
            "recency_days": "7",
        },
        search_provider=provider,
    )

    assert result["success"] is True
    assert result["query"] == "Paper Notes"
    assert result["sources"][0]["url"] == "https://example.com"


def test_register_web_search_tool_is_read_only_custom_group():
    registry = ToolRegistry()

    register_web_search_tool(registry, search_provider=lambda **kwargs: {"success": True})
    register_web_fetch_tool(registry)

    definition = registry.get("web_search")
    assert definition is not None
    assert definition.toolset == "web_search"
    assert definition.read_only is True
    assert definition.kind == "search"
    assert registry.get_group("web_search").display_name == "Custom Web Search"
    assert registry.tool_names_for_toolset("web_search") == ["web_fetch", "web_search"]


def test_tavily_web_search_normalizes_response():
    def transport(endpoint, payload, api_key):
        assert endpoint == "https://api.tavily.com/search"
        assert api_key == "tvly-test"
        assert payload["query"] == "Paper Notes"
        assert payload["max_results"] == 2
        assert payload["include_domains"] == ["example.com"]
        return {
            "answer": "A short answer.",
            "results": [
                {"title": "One", "url": "https://example.com/one", "content": "Snippet one."},
                {"title": "Two", "url": "https://example.com/two", "content": "Snippet two."},
                {"title": "Three", "url": "https://example.com/three", "content": "Snippet three."},
            ],
        }

    result = TavilyWebSearch(api_key="tvly-test", transport=transport)(
        query="Paper Notes",
        limit=2,
        allowed_domains=["example.com"],
        recency_days=None,
        include_summary=True,
    )

    assert result["success"] is True
    assert result["provider"] == "tavily"
    assert result["answer"] == "A short answer."
    assert [source["url"] for source in result["sources"]] == [
        "https://example.com/one",
        "https://example.com/two",
    ]


def test_brave_web_search_normalizes_response():
    def transport(endpoint, params, api_key):
        assert endpoint == "https://api.search.brave.com/res/v1/web/search"
        assert api_key == "brave-test"
        assert params["q"] == "(site:example.com) Paper Notes"
        assert params["count"] == "2"
        assert params["freshness"] == "pw"
        return {
            "web": {
                "results": [
                    {"title": "One", "url": "https://example.com/one", "description": "Snippet one."},
                    {"title": "Two", "url": "https://example.com/two", "description": "Snippet two."},
                    {"title": "Three", "url": "https://example.com/three", "description": "Snippet three."},
                ],
            },
        }

    result = BraveWebSearch(api_key="brave-test", transport=transport)(
        query="Paper Notes",
        limit=2,
        allowed_domains=["example.com"],
        recency_days=7,
        include_summary=True,
    )

    assert result["success"] is True
    assert result["provider"] == "brave"
    assert result["answer"] == "Snippet one. Snippet two."
    assert [source["url"] for source in result["sources"]] == [
        "https://example.com/one",
        "https://example.com/two",
    ]


def test_web_search_requires_tavily_key_without_native_provider(monkeypatch, tmp_path):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("PAPER_NOTES_ENV_PATHS", str(tmp_path / "missing.env"))
    monkeypatch.setenv("PAPER_NOTES_SECRETS_PATH", str(tmp_path / "secrets.env"))

    result = ConfiguredWebSearch()(query="Paper Notes")

    assert result["success"] is False
    assert result["code"] == "web_search_provider_required"


def test_configured_web_search_prefers_tavily_when_multiple_custom_providers_enabled(monkeypatch, tmp_path):
    settings_dir = tmp_path / ".paper-notes"
    settings_dir.mkdir()
    (settings_dir / "tool-settings.json").write_text(json.dumps({
        "toolsets": {
            "web_search": {
                "enabled": True,
                "custom_provider": {
                    "Tavily": {"enabled": True},
                    "Brave": {"enabled": True},
                },
            },
        },
    }), encoding="utf-8")
    monkeypatch.setattr(web_search_providers, "LOCAL_STATE_DIR", settings_dir)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-test")

    class FakeTavily:
        def __init__(self, api_key):
            assert api_key == "tvly-test"

        def __call__(self, **kwargs):
            return {"success": True, "provider": "tavily", "query": kwargs["query"]}

    def fail_brave(*args, **kwargs):
        raise AssertionError("Brave should not be used when Tavily is enabled.")

    monkeypatch.setattr(web_search_providers, "TavilyWebSearch", FakeTavily)
    monkeypatch.setattr(web_search_providers, "BraveWebSearch", fail_brave)

    result = ConfiguredWebSearch()(query="Paper Notes")

    assert result["success"] is True
    assert result["provider"] == "tavily"
