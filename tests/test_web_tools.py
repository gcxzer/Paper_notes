from __future__ import annotations

from datetime import datetime, timezone
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from agent_runtime import AgentService, AgentServiceRequest
from agent_runtime.run_trace import model_response_trace_events
from agent_sessions import AgentSessionStore
from app_config import AppConfig
from tools import ToolContext, create_tools, tool_name
from tools.web_fetch import tool as web_fetch_tool
from tools.web_fetch.security import UrlValidationResult
from tools.web_search import providers as web_search_providers
from tools.web_search.tool import web_search


def _config(provider: str = "openai", model: str = "gpt-5.5") -> AppConfig:
    return AppConfig(
        data={
            "models": {
                "default": "main",
                "main": {
                    "provider": provider,
                    "name": model,
                    "options": {},
                },
            },
        },
        path=None,
    )


def _tool_names(context: ToolContext) -> list[str]:
    return [tool_name(tool) for tool in create_tools(context)]


def test_openai_tools_use_native_web_search_and_fetch(monkeypatch):
    monkeypatch.setattr(web_search_providers, "configured_web_search_available", lambda: False)
    names = _tool_names(ToolContext(provider_name="openai", model="gpt-5.5"))

    assert "web_search" in names
    assert "web_fetch" in names


def test_local_web_search_is_hidden_without_api_key_for_models_without_native_search(monkeypatch):
    monkeypatch.setattr(web_search_providers, "configured_web_search_available", lambda: False)
    names = _tool_names(ToolContext(provider_name="deepseek", model="deepseek-v4"))

    assert "web_search" not in names
    assert "web_fetch" in names


def test_local_web_search_is_visible_with_api_key_when_native_search_is_unavailable(monkeypatch):
    monkeypatch.setattr(web_search_providers, "configured_web_search_available", lambda: True)
    names = _tool_names(ToolContext(provider_name="deepseek", model="deepseek-v4"))

    assert "web_search" in names
    assert "web_fetch" in names


def test_non_vision_models_hide_paper_visual_tools(monkeypatch):
    monkeypatch.setattr(web_search_providers, "configured_web_search_available", lambda: False)

    spark_names = _tool_names(ToolContext(provider_name="codex-oauth", model="gpt-5.3-codex-spark"))
    deepseek_names = _tool_names(ToolContext(provider_name="deepseek", model="deepseek-v4"))
    openai_names = _tool_names(ToolContext(provider_name="openai", model="gpt-5.5"))

    assert "inspect_paper_visuals" not in spark_names
    assert "inspect_paper_visuals" not in deepseek_names
    assert "inspect_paper_visuals" in openai_names


def test_web_search_uses_injected_provider_and_normalizes_args():
    captured = {}

    def provider(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "query": kwargs["query"],
            "answer": "",
            "sources": [],
            "citations": [],
            "provider": "fake",
        }

    result = web_search(
        {
            "query": "OpenAI news",
            "limit": 99,
            "allowed_domains": ["openai.com", "openai.com", ""],
            "recency_days": "7",
            "include_summary": False,
        },
        search_provider=provider,
    )

    assert result["success"] is True
    assert captured == {
        "query": "OpenAI news",
        "limit": 10,
        "allowed_domains": ["openai.com"],
        "recency_days": 7,
        "include_summary": False,
    }


def test_web_fetch_blocks_localhost():
    result = web_fetch_tool.web_fetch({"url": "http://localhost:8765/private"})

    assert result["success"] is False
    assert result["code"] == "blocked_url"


def test_web_fetch_extracts_html_without_network(monkeypatch):
    monkeypatch.setattr(
        web_fetch_tool,
        "validate_public_http_url",
        lambda url: UrlValidationResult(True, url=str(url)),
    )
    monkeypatch.setattr(
        web_fetch_tool,
        "_fetch_bytes",
        lambda _url: {
            "data": b"<html><head><title>Example</title></head><body><h1>Hello</h1><p>Readable text.</p><a href='https://example.com/a'>A link</a></body></html>",
            "final_url": "https://example.com/page",
            "content_type": "text/html; charset=utf-8",
        },
    )

    result = web_fetch_tool.web_fetch({
        "url": "https://example.com/page",
        "max_chars": 20,
        "include_links": True,
        "format": "markdown",
    })

    assert result["success"] is True
    assert result["title"] == "Example"
    assert result["text"].startswith("# Hello")
    assert result["truncated"] is True
    assert result["links"] == [{"url": "https://example.com/a", "text": "A link"}]


def test_agent_service_filters_disabled_tools(tmp_path):
    web_tool = StructuredTool.from_function(func=lambda query: query, name="web_search", description="Search the web.")
    fetch_tool = StructuredTool.from_function(func=lambda url: url, name="web_fetch", description="Fetch a URL.")
    service = AgentService(
        app_config=_config(),
        session_store=AgentSessionStore(tmp_path / "sessions"),
        chat_model=FakeMessagesListChatModel(responses=[AIMessage(content="Done.")]),
        extra_tools=[web_tool, fetch_tool],
        use_default_tools=False,
    )

    tools = service._tools_for_request(AgentServiceRequest(
        message="search",
        disabled_tools=("web_search",),
    ))

    assert [tool.name for tool in tools] == ["web_fetch"]


def test_agent_service_disabled_web_search_hides_native_and_custom_web_search(tmp_path):
    web_tool = StructuredTool.from_function(func=lambda query: query, name="web_search", description="Search the web.")
    fetch_tool = StructuredTool.from_function(func=lambda url: url, name="web_fetch", description="Fetch a URL.")
    service = AgentService(
        app_config=_config(provider="openai", model="gpt-5.5"),
        session_store=AgentSessionStore(tmp_path / "sessions"),
        chat_model=FakeMessagesListChatModel(responses=[AIMessage(content="Done.")]),
        extra_tools=[web_tool, fetch_tool],
        use_default_tools=False,
    )
    request = AgentServiceRequest(
        message="search",
        provider="openai",
        model="gpt-5.5",
        disabled_tools=("web_search",),
    )
    model_config = service._model_config_for_request(request, session=None)

    tools = service._tools_for_request(request, model_config=model_config)

    assert tools == [fetch_tool]


def test_agent_service_layers_context_tools_custom_tools_and_disabled_filter(monkeypatch, tmp_path):
    monkeypatch.setattr(web_search_providers, "configured_web_search_available", lambda: False)
    custom_tool = StructuredTool.from_function(
        func=lambda query: query,
        name="custom_note_tool",
        description="Custom tool.",
    )
    custom_web_tool = StructuredTool.from_function(
        func=lambda query: query,
        name="web_search",
        description="Custom web search.",
    )
    service = AgentService(
        app_config=_config(provider="openai", model="gpt-5.5"),
        session_store=AgentSessionStore(tmp_path / "sessions"),
        chat_model=FakeMessagesListChatModel(responses=[AIMessage(content="Done.")]),
        extra_tools=[custom_tool, custom_web_tool],
        use_default_tools=True,
    )
    request = AgentServiceRequest(
        message="search",
        provider="openai",
        model="gpt-5.5",
        disabled_tools=("web_search",),
    )
    model_config = service._model_config_for_request(request, session=None)

    tools = service._tools_for_request(request, model_config=model_config)
    names = {tool_name(tool) for tool in tools}

    assert "custom_note_tool" in names
    assert "web_fetch" in names
    assert "web_search" not in names


def test_agent_service_exposes_native_web_search_for_default_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(web_search_providers, "configured_web_search_available", lambda: False)
    service = AgentService(
        app_config=_config(provider="openai", model="gpt-5.5"),
        session_store=AgentSessionStore(tmp_path / "sessions"),
        chat_model=FakeMessagesListChatModel(responses=[AIMessage(content="Done.")]),
        use_default_tools=True,
    )
    request = AgentServiceRequest(message="search", provider="openai", model="gpt-5.5")
    model_config = service._model_config_for_request(request, session=None)

    tools = service._tools_for_request(request, model_config=model_config, model_supports_tools=True)

    assert {"web_search", "web_fetch"} <= {tool_name(tool) for tool in tools}


def test_model_response_trace_extracts_provider_native_web_search():
    message = AIMessage(
        content=[
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {
                    "query": "OpenAI news",
                    "sources": [{"url": "https://openai.com/news", "title": "OpenAI News"}],
                },
            },
            {
                "type": "text",
                "text": "Result",
                "annotations": [{"type": "url_citation", "url": "https://openai.com/news", "title": "OpenAI News"}],
            },
        ],
        response_metadata={"model_provider": "openai"},
    )

    events = model_response_trace_events([message], at=datetime(2026, 6, 14, tzinfo=timezone.utc))

    assert events == [{
        "type": "model_response",
        "stage": "model_response",
        "message": "Model provider returned a response with 1 web search call and 1 source.",
        "at": "2026-06-14T00:00:00+00:00",
        "data": {
            "turn": 1,
            "source": "openai",
            "webSearchCallCount": 1,
            "webSearchSourceCount": 1,
            "webSearchQueries": ["OpenAI news"],
        },
    }]
