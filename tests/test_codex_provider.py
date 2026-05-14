from __future__ import annotations

from types import SimpleNamespace

import pytest

from model_providers import CodexModelProvider, ModelProviderConfigError, ModelRequest, ModelStreamEvent


PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class FakeResponses:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response) -> None:
        self.responses = FakeResponses(response)


class FakeStreamingResponses:
    def __init__(self, events) -> None:
        self.events = list(events)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.events)


class FakeStreamingClient:
    def __init__(self, events) -> None:
        self.responses = FakeStreamingResponses(events)


def test_codex_provider_uses_responses_api_and_omits_max_output_tokens() -> None:
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Hello from Codex", usage=None)
    client = FakeClient(response)
    provider = CodexModelProvider(client=client, default_model="gpt-5.5")

    result = provider.generate(ModelRequest(
        messages=[{"role": "user", "content": "Hi"}],
        max_output_tokens=123,
    ))

    payload = client.responses.calls[0]
    assert payload["model"] == "gpt-5.5"
    assert payload["input"] == [{"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}]
    assert payload["store"] is False
    assert payload["stream"] is True
    assert payload["instructions"] == ""
    assert "max_output_tokens" not in payload
    assert result.content == "Hello from Codex"


def test_codex_provider_preflight_rejects_unsupported_payload_fields() -> None:
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Hello from Codex", usage=None)
    client = FakeClient(response)
    provider = CodexModelProvider(client=client, default_model="gpt-5.5")

    with pytest.raises(ValueError, match="unsupported field"):
        provider.generate(ModelRequest(
            messages=[{"role": "user", "content": "Hi"}],
            request_options={"unsupported_codex_field": True},
        ))

    assert client.responses.calls == []


def test_codex_provider_supports_image_input() -> None:
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Hello from Codex", usage=None)
    client = FakeClient(response)
    provider = CodexModelProvider(client=client, default_model="gpt-5.5")

    result = provider.generate(ModelRequest(
        messages=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "What is this?"},
                {"type": "input_image", "image_url": PNG_DATA_URL},
            ],
        }],
        max_output_tokens=123,
    ))

    payload = client.responses.calls[0]
    content = payload["input"][0]["content"]
    assert "max_output_tokens" not in payload
    assert content[0] == {"type": "input_text", "text": "What is this?"}
    assert content[1] == {"type": "input_image", "image_url": PNG_DATA_URL}
    assert result.content == "Hello from Codex"


def test_codex_provider_rejects_image_generation_tool() -> None:
    response = SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[],
        output_text="",
        usage=None,
    )
    client = FakeClient(response)
    provider = CodexModelProvider(client=client, default_model="gpt-5.5")

    with pytest.raises(ModelProviderConfigError, match="not configured for image generation"):
        provider.generate(ModelRequest(
            messages=[{"role": "user", "content": "Generate an image"}],
            tools=[{"type": "image_generation", "size": "1024x1024"}],
        ))

    assert client.responses.calls == []


def test_codex_provider_allows_provider_native_web_search_preflight() -> None:
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Search done", usage=None)
    client = FakeClient(response)
    provider = CodexModelProvider(client=client, default_model="gpt-5.5")

    result = provider.generate(ModelRequest(
        messages=[{"role": "user", "content": "Search"}],
        request_options={"_paper_notes_provider_native_web_search": True},
    ))

    payload = client.responses.calls[0]
    assert payload["tools"] == [{"type": "web_search"}]
    assert payload["tool_choice"] == "auto"
    assert "web_search_call.action.sources" in payload["include"]
    assert result.content == "Search done"


def test_codex_provider_collects_streamed_text_delta() -> None:
    terminal = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="", usage=None)
    client = FakeStreamingClient([
        SimpleNamespace(type="response.output_text.delta", delta="Hello"),
        SimpleNamespace(type="response.output_text.delta", delta=" from Codex"),
        SimpleNamespace(type="response.completed", response=terminal),
    ])
    provider = CodexModelProvider(client=client, default_model="gpt-5.4")

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))

    assert client.responses.calls[0]["stream"] is True
    assert result.content == "Hello from Codex"


def test_codex_provider_stream_generate_emits_text_delta_events() -> None:
    terminal = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="", usage=None)
    client = FakeStreamingClient([
        SimpleNamespace(type="response.output_text.delta", delta="Hi"),
        SimpleNamespace(type="response.output_text.delta", delta=" there"),
        SimpleNamespace(type="response.completed", response=terminal),
    ])
    provider = CodexModelProvider(client=client, default_model="gpt-5.4")
    events: list[ModelStreamEvent] = []

    result = provider.stream_generate(
        ModelRequest(messages=[{"role": "user", "content": "Hi"}]),
        event_sink=events.append,
    )

    assert client.responses.calls[0]["stream"] is True
    assert result.content == "Hi there"
    assert [event.delta for event in events] == ["Hi", " there"]
