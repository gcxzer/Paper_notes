from __future__ import annotations

from types import SimpleNamespace

import pytest

from model_providers import AnthropicModelProvider, ModelProviderAPIError, ModelRequest
from model_providers.anthropic.provider import build_anthropic_payload


class FakeAnthropicResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeAnthropicSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_anthropic_provider_generates_text_response():
    session = FakeAnthropicSession(FakeAnthropicResponse(payload={
        "content": [{"type": "text", "text": "Hello from Claude."}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 3, "output_tokens": 4},
    }))
    provider = AnthropicModelProvider(api_key="test-key", default_model="claude-test", session=session)

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))

    assert result.content == "Hello from Claude."
    assert result.finish_reason == "stop"
    assert result.usage.total_tokens == 7
    assert session.calls[0]["url"].endswith("/messages")
    assert session.calls[0]["headers"]["x-api-key"] == "test-key"
    assert session.calls[0]["json"]["model"] == "claude-test"


def test_anthropic_provider_translates_tool_call_response():
    session = FakeAnthropicSession(FakeAnthropicResponse(payload={
        "content": [{"type": "tool_use", "id": "toolu_1", "name": "search_notes", "input": {"query": "attention"}}],
        "stop_reason": "tool_use",
    }))
    provider = AnthropicModelProvider(api_key="test-key", default_model="claude-test", session=session)

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Search"}]))

    assert result.finish_reason == "tool_calls"
    assert result.tool_calls[0].id == "toolu_1"
    assert result.tool_calls[0].name == "search_notes"
    assert '"attention"' in result.tool_calls[0].arguments


def test_anthropic_payload_translates_tools_tool_results_and_images():
    request = ModelRequest(
        instructions="You help with papers.",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Describe this."},
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,aGVsbG8=",
                    },
                ],
            },
            {
                "role": "assistant",
                "tool_calls": [SimpleNamespace(
                    id="call_1",
                    function=SimpleNamespace(name="lookup", arguments='{"query":"x"}'),
                )],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'},
        ],
        tools=[{
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up something.",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }],
        max_output_tokens=123,
    )

    payload = build_anthropic_payload(request, model="claude-test")

    assert payload["system"] == "You help with papers."
    assert payload["max_tokens"] == 123
    assert payload["tools"][0]["name"] == "lookup"
    assert payload["tools"][0]["input_schema"]["properties"]["query"]["type"] == "string"
    assert payload["messages"][0]["content"][1]["type"] == "image"
    assert payload["messages"][0]["content"][1]["source"]["type"] == "base64"
    assert payload["messages"][1]["content"][0]["type"] == "tool_use"
    assert payload["messages"][2]["content"][0]["type"] == "tool_result"
    assert payload["messages"][2]["content"][0]["tool_use_id"] == "call_1"


def test_anthropic_payload_forwards_adaptive_thinking_and_output_effort():
    request = ModelRequest(
        messages=[{"role": "user", "content": "Think."}],
        request_options={
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": "medium"},
            "temperature": 0.7,
        },
    )

    payload = build_anthropic_payload(request, model="claude-sonnet-4-6")

    assert payload["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert payload["output_config"] == {"effort": "medium"}
    assert "temperature" not in payload


def test_anthropic_payload_adds_native_web_search_tool():
    request = ModelRequest(
        messages=[{"role": "user", "content": "Find current sources."}],
        request_options={"_paper_notes_native_web_search": True},
    )

    payload = build_anthropic_payload(request, model="claude-sonnet-4-6")

    assert {"type": "web_search_20260209", "name": "web_search"} in payload["tools"]


def test_anthropic_payload_replays_thinking_blocks_before_tool_calls():
    request = ModelRequest(
        messages=[{
            "role": "assistant",
            "content": "",
            "provider_data": {
                "anthropic_thinking_blocks": [{
                    "type": "thinking",
                    "thinking": "I should inspect the note.",
                    "signature": "sig_123",
                }]
            },
            "tool_calls": [SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name="lookup", arguments='{"query":"x"}'),
            )],
        }],
        request_options={"thinking": {"type": "adaptive"}},
    )

    payload = build_anthropic_payload(request, model="claude-sonnet-4-6")

    content = payload["messages"][0]["content"]
    assert content[0] == {
        "type": "thinking",
        "thinking": "I should inspect the note.",
        "signature": "sig_123",
    }
    assert content[1]["type"] == "tool_use"


def test_anthropic_response_extracts_thinking_as_work_trace_only():
    session = FakeAnthropicSession(FakeAnthropicResponse(payload={
        "content": [
            {"type": "thinking", "thinking": "I should reason.", "signature": "sig_1"},
            {"type": "redacted_thinking", "data": "encrypted"},
            {"type": "text", "text": "Final."},
        ],
        "stop_reason": "end_turn",
    }))
    provider = AnthropicModelProvider(api_key="test-key", default_model="claude-sonnet-4-6", session=session)

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))

    assert result.content == "Final."
    assert result.provider_data["work_trace_items"] == [{
        "type": "summary",
        "text": "I should reason.",
        "source": "provider",
    }]
    assert result.provider_data["anthropic_thinking_blocks"][0]["signature"] == "sig_1"
    assert result.provider_data["anthropic_thinking_blocks"][1] == {"type": "redacted_thinking", "data": "encrypted"}


def test_anthropic_response_extracts_web_search_metadata():
    session = FakeAnthropicSession(FakeAnthropicResponse(payload={
        "content": [
            {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "paper notes"}},
            {
                "type": "web_search_tool_result",
                "tool_use_id": "srv_1",
                "content": [{"url": "https://example.com/a", "title": "Example A"}],
            },
            {
                "type": "text",
                "text": "Grounded answer.",
                "citations": [{
                    "type": "web_search_result_location",
                    "url": "https://example.com/a",
                    "title": "Example A",
                    "cited_text": "Grounded",
                    "start_index": 0,
                    "end_index": 8,
                }],
            },
        ],
        "stop_reason": "end_turn",
    }))
    provider = AnthropicModelProvider(api_key="test-key", default_model="claude-sonnet-4-6", session=session)

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))

    assert result.content == "Grounded answer."
    assert result.provider_data["web_search_calls"][0]["id"] == "srv_1"
    assert result.provider_data["web_search_sources"] == [{
        "url": "https://example.com/a",
        "title": "Example A",
        "snippet": "",
    }]
    assert result.provider_data["web_search_citations"][0]["url"] == "https://example.com/a"


def test_anthropic_provider_raises_api_error():
    session = FakeAnthropicSession(FakeAnthropicResponse(
        status_code=401,
        payload={"error": {"message": "invalid api key"}},
        text="invalid api key",
    ))
    provider = AnthropicModelProvider(api_key="test-key", default_model="claude-test", session=session)

    with pytest.raises(ModelProviderAPIError, match="Anthropic HTTP 401"):
        provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))
