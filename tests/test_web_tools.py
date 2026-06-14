from __future__ import annotations

from datetime import datetime, timezone

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from agent_runtime import AgentService, AgentServiceRequest
from agent_runtime.service import _model_response_trace_events
from agent_sessions import AgentSessionStore
from app_config import AppConfig
from tools import create_tools
from tools.web_fetch import tool as web_fetch_tool
from tools.web_fetch.security import UrlValidationResult
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


def test_default_tools_include_web_search_and_fetch():
    names = [tool.name for tool in create_tools()]

    assert "web_search" in names
    assert "web_fetch" in names


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
        tools=[web_tool, fetch_tool],
        use_default_tools=False,
    )

    tools = service._tools_for_request(AgentServiceRequest(
        message="search",
        disabled_tools=("web_search",),
    ))

    assert [tool.name for tool in tools] == ["web_fetch"]


@pytest.mark.parametrize(
    ("provider", "model", "native_tool"),
    [
        ("openai", "gpt-5.5", {"type": "web_search"}),
    ],
)
def test_agent_service_adds_provider_native_web_search(provider, model, native_tool, tmp_path):
    web_tool = StructuredTool.from_function(func=lambda query: query, name="web_search", description="Search the web.")
    fetch_tool = StructuredTool.from_function(func=lambda url: url, name="web_fetch", description="Fetch a URL.")
    service = AgentService(
        app_config=_config(provider=provider, model=model),
        session_store=AgentSessionStore(tmp_path / "sessions"),
        chat_model=FakeMessagesListChatModel(responses=[AIMessage(content="Done.")]),
        tools=[web_tool, fetch_tool],
        use_default_tools=False,
    )
    request = AgentServiceRequest(
        message="search",
        provider=provider,
        model=model,
        model_options={"_paper_notes_native_web_search": True},
        disabled_tools=("web_search",),
    )
    model_config = service._model_config_for_request(request, session=None)

    tools = service._tools_for_request(request, model_config=model_config)

    assert tools == [native_tool, fetch_tool]


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

    events = _model_response_trace_events([message], at=datetime(2026, 6, 14, tzinfo=timezone.utc))

    assert events == [{
        "type": "model_response",
        "stage": "model_response",
        "message": "Model provider returned a response with 1 web search call and 1 source.",
        "at": "2026-06-14T00:00:00+00:00",
        "data": {
            "turn": 1,
            "source": "openai",
            "web_search_call_count": 1,
            "web_search_source_count": 1,
            "web_search_queries": ["OpenAI news"],
        },
    }]
