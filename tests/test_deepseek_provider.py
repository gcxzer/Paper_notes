from __future__ import annotations

from types import SimpleNamespace

import pytest

from model_providers import DeepSeekModelProvider, ModelProviderAPIError, ModelRequest
from model_providers.deepseek.provider import build_deepseek_payload, normalize_deepseek_response


class FakeDeepSeekResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeDeepSeekSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_deepseek_provider_generates_text_response():
    session = FakeDeepSeekSession(FakeDeepSeekResponse(payload={
        "choices": [{"message": {"role": "assistant", "content": "Hello from DeepSeek."}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    }))
    provider = DeepSeekModelProvider(api_key="test-key", default_model="deepseek-test", session=session)

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))

    assert result.content == "Hello from DeepSeek."
    assert result.finish_reason == "stop"
    assert result.usage.total_tokens == 7
    assert session.calls[0]["url"].endswith("/chat/completions")
    assert session.calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert session.calls[0]["json"]["model"] == "deepseek-test"


def test_deepseek_provider_translates_tool_call_response():
    session = FakeDeepSeekSession(FakeDeepSeekResponse(payload={
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "paper_notes_search", "arguments": '{"query":"attention"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }))
    provider = DeepSeekModelProvider(api_key="test-key", default_model="deepseek-test", session=session)

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Search"}]))

    assert result.finish_reason == "tool_calls"
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "paper_notes_search"
    assert '"attention"' in result.tool_calls[0].arguments


def test_deepseek_payload_translates_tools_and_tool_results():
    request = ModelRequest(
        instructions="You help with papers.",
        messages=[
            {"role": "user", "content": [{"type": "input_text", "text": "Search this."}]},
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

    payload = build_deepseek_payload(request, model="deepseek-test")

    assert payload["model"] == "deepseek-test"
    assert payload["max_tokens"] == 123
    assert payload["messages"][0] == {"role": "system", "content": "You help with papers."}
    assert payload["messages"][1] == {"role": "user", "content": "Search this."}
    assert payload["messages"][2]["tool_calls"][0]["function"]["name"] == "lookup"
    assert payload["messages"][3]["tool_call_id"] == "call_1"
    assert payload["tools"][0]["function"]["name"] == "lookup"


def test_deepseek_payload_forwards_reasoning_and_thinking_options():
    request = ModelRequest(
        messages=[{"role": "user", "content": "Think carefully."}],
        request_options={
            "reasoning_effort": "high",
            "thinking": {"type": "enabled"},
        },
    )

    payload = build_deepseek_payload(request, model="deepseek-v4-pro")

    assert payload["reasoning_effort"] == "high"
    assert payload["thinking"] == {"type": "enabled"}


def test_deepseek_payload_enables_thinking_when_reasoning_effort_is_set():
    request = ModelRequest(
        messages=[{"role": "user", "content": "Think carefully."}],
        request_options={"reasoning_effort": "max"},
    )

    payload = build_deepseek_payload(request, model="deepseek-v4-pro")

    assert payload["reasoning_effort"] == "max"
    assert payload["thinking"] == {"type": "enabled"}


def test_deepseek_payload_forwards_disabled_thinking_option():
    request = ModelRequest(
        messages=[{"role": "user", "content": "Answer directly."}],
        request_options={"thinking": {"type": "disabled"}},
    )

    payload = build_deepseek_payload(request, model="deepseek-v4-flash")

    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload


def test_deepseek_payload_rejects_unsupported_reasoning_effort_values():
    low_payload = build_deepseek_payload(
        ModelRequest(
            messages=[{"role": "user", "content": "Think carefully."}],
            request_options={"reasoning_effort": "low"},
        ),
        model="deepseek-v4-pro",
    )
    max_payload = build_deepseek_payload(
        ModelRequest(
            messages=[{"role": "user", "content": "Think carefully."}],
            request_options={"reasoning_effort": "xhigh"},
        ),
        model="deepseek-v4-pro",
    )

    assert "reasoning_effort" not in low_payload
    assert "thinking" not in low_payload
    assert "reasoning_effort" not in max_payload
    assert "thinking" not in max_payload


def test_deepseek_payload_replays_reasoning_content_for_tool_call_turns():
    request = ModelRequest(
        messages=[
            {"role": "user", "content": "Search."},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "I should use the search tool.",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"query":"x"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'},
        ],
    )

    payload = build_deepseek_payload(request, model="deepseek-v4-pro")

    assistant_message = payload["messages"][1]
    assert assistant_message["reasoning_content"] == "I should use the search tool."
    assert assistant_message["tool_calls"][0]["id"] == "call_1"


def test_deepseek_response_preserves_reasoning_content_for_replay():
    result = normalize_deepseek_response(
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "I should call a tool.",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        },
        model="deepseek-v4-pro",
    )

    assert result.provider_data["reasoning_content"] == "I should call a tool."
    assert result.finish_reason == "tool_calls"


def test_deepseek_provider_raises_api_error():
    session = FakeDeepSeekSession(FakeDeepSeekResponse(
        status_code=401,
        payload={"error": {"message": "invalid api key"}},
        text="invalid api key",
    ))
    provider = DeepSeekModelProvider(api_key="test-key", default_model="deepseek-test", session=session)

    with pytest.raises(ModelProviderAPIError, match="DeepSeek HTTP 401"):
        provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))
