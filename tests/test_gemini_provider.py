from __future__ import annotations

from types import SimpleNamespace

import pytest

from model_providers import GeminiModelProvider, ModelProviderAPIError, ModelRequest
from model_providers.gemini.provider import build_gemini_payload


class FakeGeminiResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeGeminiSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_gemini_provider_generates_text_response():
    session = FakeGeminiSession(FakeGeminiResponse(payload={
        "candidates": [{"content": {"parts": [{"text": "Hello from Gemini."}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4, "totalTokenCount": 7},
    }))
    provider = GeminiModelProvider(api_key="test-key", default_model="gemini-3-flash-preview", session=session)

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))

    assert result.content == "Hello from Gemini."
    assert result.finish_reason == "stop"
    assert result.usage.total_tokens == 7
    assert session.calls[0]["url"].endswith("/models/gemini-3-flash-preview:generateContent")
    assert session.calls[0]["params"] == {"key": "test-key"}


def test_gemini_provider_translates_tool_call_response():
    session = FakeGeminiSession(FakeGeminiResponse(payload={
        "candidates": [{
            "content": {"parts": [{"functionCall": {"name": "search_notes", "args": {"query": "attention"}}, "thoughtSignature": "sig_123"}]},
            "finishReason": "STOP",
        }],
    }))
    provider = GeminiModelProvider(api_key="test-key", default_model="gemini-3-flash-preview", session=session)

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Search"}]))

    assert result.finish_reason == "tool_calls"
    assert result.tool_calls[0].name == "search_notes"
    assert '"attention"' in result.tool_calls[0].arguments
    assert result.tool_calls[0].provider_data["thought_signature"] == "sig_123"


def test_gemini_payload_sanitizes_tools_and_preserves_tool_result_names():
    request = ModelRequest(
        messages=[
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
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "additionalProperties": False}},
                    "additionalProperties": False,
                },
            },
        }],
    )

    payload = build_gemini_payload(request, model="gemini-test")

    declaration = payload["tools"][0]["functionDeclarations"][0]
    assert declaration["parameters"] == {"type": "object", "properties": {"query": {"type": "string"}}}
    assert payload["contents"][1]["parts"][0]["functionResponse"]["name"] == "lookup"


def test_gemini_payload_preserves_thought_signature_for_tool_calls():
    request = ModelRequest(
        messages=[
            {
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_1",
                    "thoughtSignature": "sig_123",
                    "function": {"name": "lookup", "arguments": '{"query":"x"}'},
                }],
            },
        ],
    )

    payload = build_gemini_payload(request, model="gemini-3-flash-preview")

    assert payload["contents"][0]["parts"][0]["thoughtSignature"] == "sig_123"


def test_gemini_payload_adds_native_google_search_tool():
    request = ModelRequest(
        messages=[{"role": "user", "content": "Find current sources."}],
        request_options={"_paper_notes_native_web_search": True},
    )

    payload = build_gemini_payload(request, model="gemini-3-flash-preview")

    assert {"googleSearch": {}} in payload["tools"]
    assert "toolConfig" not in payload


def test_gemini_provider_extracts_thought_summaries_from_work_trace():
    session = FakeGeminiSession(FakeGeminiResponse(payload={
        "candidates": [{
            "content": {"parts": [
                {"text": "I should inspect the paper first.", "thought": True},
                {"text": "Final answer."},
            ]},
            "finishReason": "STOP",
        }],
    }))
    provider = GeminiModelProvider(api_key="test-key", default_model="gemini-3-flash-preview", session=session)

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))

    assert result.content == "Final answer."
    assert result.provider_data["work_trace_items"] == [{
        "type": "summary",
        "text": "I should inspect the paper first.",
        "source": "provider",
    }]


def test_gemini_provider_extracts_grounding_metadata():
    session = FakeGeminiSession(FakeGeminiResponse(payload={
        "candidates": [{
            "content": {"parts": [{"text": "Grounded answer."}]},
            "finishReason": "STOP",
            "groundingMetadata": {
                "webSearchQueries": ["paper notes"],
                "groundingChunks": [
                    {"web": {"uri": "https://example.com/a", "title": "Example A"}},
                ],
                "groundingSupports": [
                    {
                        "segment": {"text": "Grounded answer", "startIndex": 0, "endIndex": 15},
                        "groundingChunkIndices": [0],
                    },
                ],
            },
        }],
    }))
    provider = GeminiModelProvider(api_key="test-key", default_model="gemini-3-flash-preview", session=session)

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))

    assert result.provider_data["web_search_calls"] == [{"queries": ["paper notes"]}]
    assert result.provider_data["web_search_sources"] == [{
        "title": "Example A",
        "url": "https://example.com/a",
        "snippet": "",
    }]
    assert result.provider_data["web_search_citations"][0]["url"] == "https://example.com/a"


def test_gemini_provider_rejects_non_gemini_3_text_models():
    session = FakeGeminiSession(FakeGeminiResponse(payload={}))
    provider = GeminiModelProvider(api_key="test-key", default_model="gemini-2.5-flash", session=session)

    with pytest.raises(Exception, match="only supports Gemini 3 text models"):
        provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))


def test_gemini_provider_raises_api_error():
    session = FakeGeminiSession(FakeGeminiResponse(
        status_code=429,
        payload={"error": {"message": "quota exceeded"}},
        text="quota exceeded",
    ))
    provider = GeminiModelProvider(api_key="test-key", default_model="gemini-3-flash-preview", session=session)

    with pytest.raises(ModelProviderAPIError, match="Gemini HTTP 429"):
        provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))
