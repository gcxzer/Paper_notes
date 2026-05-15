from __future__ import annotations

from types import SimpleNamespace
from io import BytesIO
import base64

import pytest

from media import MediaStore
from model_providers.profiles import capabilities_for_provider_model, get_provider_profile
from model_providers import (
    ModelProviderAPIError,
    ModelProviderConfigError,
    ModelRequest,
    ModelStreamEvent,
    OpenAIModelProvider,
)


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


class RaisingResponses:
    def create(self, **kwargs):
        raise FakeAPIError("context length exceeded", status_code=400, body={"error": "too many tokens"})


class QuotaRaisingResponses:
    def create(self, **kwargs):
        raise FakeAPIError(
            "You exceeded your current quota.",
            status_code=429,
            body={"error": {"code": "insufficient_quota", "type": "insufficient_quota", "param": None}},
        )


class ImageInputUnsupportedResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        raise FakeAPIError(
            "Model 'gpt-test' does not support image inputs. Try again with a vision model.",
            status_code=400,
            body={"error": {"message": "Model 'gpt-test' does not support image inputs.", "type": "invalid_request_error"}},
        )


class RaisingClient:
    def __init__(self) -> None:
        self.responses = RaisingResponses()


class QuotaRaisingClient:
    def __init__(self) -> None:
        self.responses = QuotaRaisingResponses()


class ImageInputUnsupportedClient:
    def __init__(self) -> None:
        self.responses = ImageInputUnsupportedResponses()


class FlakyImageResponses:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise FakeAPIError("image too large", status_code=400, body={"error": "image exceeds maximum size"})
        return self.response


class FlakyImageClient:
    def __init__(self, response) -> None:
        self.responses = FlakyImageResponses(response)


class FakeAPIError(Exception):
    def __init__(self, message: str, *, status_code: int, body: object) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def test_openai_provider_builds_responses_payload():
    response = SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[],
        output_text="Hello",
        usage=SimpleNamespace(input_tokens=10, output_tokens=3, total_tokens=13),
    )
    client = FakeClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")

    result = provider.generate(ModelRequest(
        messages=[
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ],
        tools=[{
            "type": "function",
            "function": {
                "name": "search_notes",
                "description": "Search local notes.",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }],
        max_output_tokens=256,
    ))

    payload = client.responses.calls[0]
    assert payload["model"] == "gpt-test"
    assert payload["instructions"] == "You are helpful."
    assert payload["input"] == [{"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}]
    assert payload["store"] is False
    assert payload["reasoning"]["summary"] == "auto"
    assert "reasoning.encrypted_content" in payload["include"]
    assert payload["max_output_tokens"] == 256
    assert payload["tools"][0]["name"] == "search_notes"
    assert result.content == "Hello"
    assert result.usage.total_tokens == 13


def test_openai_provider_streams_reasoning_summary_events():
    response = SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[],
        output_text="Done",
        usage=None,
    )
    events = [
        SimpleNamespace(type="response.reasoning_summary_text.delta", delta="Checking"),
        SimpleNamespace(type="response.reasoning_summary_text.done", text="Checking the note metadata."),
        SimpleNamespace(type="response.completed", response=response),
    ]
    client = FakeStreamingClient(events)
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")
    stream_events: list[ModelStreamEvent] = []

    result = provider.stream_generate(
        ModelRequest(messages=[{"role": "user", "content": "Hi"}]),
        event_sink=stream_events.append,
    )

    assert result.content == "Done"
    assert [(event.type, event.delta, event.text) for event in stream_events] == [
        ("reasoning_summary_delta", "Checking", "Checking"),
        ("reasoning_summary_done", "", "Checking the note metadata."),
    ]


def test_openai_provider_combines_static_and_ephemeral_instructions():
    response = SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[],
        output_text="Hello",
        usage=None,
    )
    client = FakeClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")

    provider.generate(ModelRequest(
        instructions="Stable Paper Notes instructions.",
        messages=[
            {"role": "system", "content": "# Runtime context\n- Current date: 2026-05-13"},
            {"role": "user", "content": "What is today?"},
        ],
    ))

    payload = client.responses.calls[0]
    assert "Stable Paper Notes instructions." in payload["instructions"]
    assert "# Runtime context" in payload["instructions"]
    assert "Current date: 2026-05-13" in payload["instructions"]
    assert payload["input"] == [{"role": "user", "content": [{"type": "input_text", "text": "What is today?"}]}]


def test_openai_provider_adds_provider_native_web_search_and_sources():
    response = SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[
            SimpleNamespace(
                type="web_search_call",
                id="ws_1",
                status="completed",
                action=SimpleNamespace(sources=[
                    SimpleNamespace(title="Example", url="https://example.com", snippet="A result."),
                ]),
            ),
            SimpleNamespace(
                type="message",
                role="assistant",
                status="completed",
                content=[
                    SimpleNamespace(
                        type="output_text",
                        text="Found it.",
                        annotations=[
                            SimpleNamespace(type="url_citation", title="Example", url="https://example.com"),
                        ],
                    ),
                ],
            ),
        ],
        output_text="Found it.",
        usage=None,
    )
    client = FakeClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")

    result = provider.generate(ModelRequest(
        messages=[{"role": "user", "content": "Search the web"}],
        request_options={"_paper_notes_provider_native_web_search": True},
    ))

    payload = client.responses.calls[0]
    assert {"type": "web_search"} in payload["tools"]
    assert payload["tool_choice"] == "auto"
    assert "web_search_call.action.sources" in payload["include"]
    assert result.content == "Found it."
    assert result.provider_data["web_search_sources"] == [{
        "title": "Example",
        "url": "https://example.com",
        "snippet": "A result.",
    }]
    assert result.provider_data["web_search_citations"][0]["url"] == "https://example.com"


def test_openai_provider_stream_generate_emits_text_delta_events():
    terminal = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="", usage=None)
    client = FakeStreamingClient([
        SimpleNamespace(type="response.output_text.delta", delta="Hel"),
        SimpleNamespace(type="response.output_text.delta", delta="lo"),
        SimpleNamespace(type="response.completed", response=terminal),
    ])
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")
    events: list[ModelStreamEvent] = []

    result = provider.stream_generate(
        ModelRequest(messages=[{"role": "user", "content": "Hi"}]),
        event_sink=events.append,
    )

    assert client.responses.calls[0]["stream"] is True
    assert result.content == "Hello"
    assert [event.delta for event in events] == ["Hel", "lo"]
    assert events[-1].text == "Hello"


def test_openai_provider_profile_exposes_image_capabilities():
    profile = get_provider_profile("openai")
    codex = get_provider_profile("codex-oauth")

    assert profile is not None
    assert profile.to_public_dict()["capabilities"]["supportsVision"] is True
    assert capabilities_for_provider_model("openai", "gpt-5.5").supports_image_generation is True
    assert codex is not None
    assert codex.to_public_dict()["capabilities"]["supportsVision"] is True
    assert capabilities_for_provider_model("codex-oauth", "gpt-5.5").supports_image_generation is False
    assert capabilities_for_provider_model("codex-oauth", "gpt-5.3-codex-spark").supports_vision is False
    assert capabilities_for_provider_model("codex-oauth", "gpt-5.3-codex-spark").image_input_mode == "unsupported"
    assert capabilities_for_provider_model("codex-oauth", "gpt-5.3-codex-spark").supports_web_search is False
    assert capabilities_for_provider_model("codex-oauth", "gpt-5.3-codex-spark").supports_reasoning_off is False


def test_openai_provider_normalizes_function_calls():
    response = SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[
            SimpleNamespace(
                type="function_call",
                id="fc_1",
                call_id="call_1",
                name="search_notes",
                arguments='{"query": "attention"}',
            ),
        ],
        output_text="",
        usage=None,
    )
    provider = OpenAIModelProvider(client=FakeClient(response), default_model="gpt-test")

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Search"}]))

    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].provider_data["response_item_id"] == "fc_1"
    assert result.tool_calls[0].name == "search_notes"
    assert result.tool_calls[0].arguments == '{"query": "attention"}'


def test_openai_provider_keeps_commentary_out_of_visible_content_when_calling_tools():
    response = SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                id="msg_1",
                role="assistant",
                status="completed",
                phase="commentary",
                content=[SimpleNamespace(type="output_text", text="Need understand. Read page 9.")],
            ),
            SimpleNamespace(
                type="function_call",
                id="fc_1",
                call_id="call_1",
                name="read_paper",
                arguments='{"action":"read_pages"}',
            ),
        ],
        output_text="",
        usage=None,
    )
    provider = OpenAIModelProvider(client=FakeClient(response), default_model="gpt-test")

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Generate image"}]))

    assert result.finish_reason == "tool_calls"
    assert not result.content
    assert len(result.tool_calls) == 1
    assert result.provider_data["codex_message_items"][0]["phase"] == "commentary"
    assert result.provider_data["work_trace_items"] == [
        {"type": "commentary", "text": "Need understand. Read page 9.", "source": "provider"},
    ]


def test_openai_provider_generates_stable_function_call_id_when_missing():
    response = SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[
            SimpleNamespace(
                type="function_call",
                id=None,
                call_id=None,
                name="search_notes",
                arguments='{"query": "attention"}',
            ),
        ],
        output_text="",
        usage=None,
    )
    provider = OpenAIModelProvider(client=FakeClient(response), default_model="gpt-test")

    first = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Search"}]))
    second = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Search"}]))

    assert first.tool_calls[0].id.startswith("call_")
    assert first.tool_calls[0].id == second.tool_calls[0].id


def test_openai_provider_maps_tool_history_to_responses_input():
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Done", usage=None)
    client = FakeClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")

    provider.generate(ModelRequest(messages=[
        {
            "role": "assistant",
            "content": "I will search.",
            "tool_calls": [{
                "id": "call_1",
                "call_id": "call_1",
                "response_item_id": "fc_1",
                "type": "function",
                "function": {"name": "search_notes", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"answer": "found"}'},
    ]))

    assert client.responses.calls[0]["input"] == [
        {"role": "assistant", "content": [{"type": "output_text", "text": "I will search."}]},
        {"type": "function_call", "call_id": "call_1", "name": "search_notes", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": '{"answer": "found"}'},
    ]


def test_openai_provider_replays_codex_reasoning_and_message_items():
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Done", usage=None)
    client = FakeClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")

    provider.generate(ModelRequest(messages=[{
        "role": "assistant",
        "content": "",
        "codex_reasoning_items": [{
            "type": "reasoning",
            "id": "rs_1",
            "encrypted_content": "opaque",
            "summary": [],
        }],
        "codex_message_items": [{
            "type": "message",
            "role": "assistant",
            "id": "msg_1",
            "status": "completed",
            "phase": "final_answer",
            "content": [{"type": "output_text", "text": "Prior answer"}],
        }],
    }]))

    assert client.responses.calls[0]["input"] == [
        {"type": "reasoning", "encrypted_content": "opaque", "summary": []},
        {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "Prior answer"}],
            "id": "msg_1",
            "phase": "final_answer",
        },
    ]


def test_openai_provider_maps_image_attachments_to_responses_input(tmp_path):
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Done", usage=None)
    client = FakeClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")
    media_store = MediaStore(tmp_path / ".paper-notes" / "media")
    artifact = media_store.create_upload(PNG_DATA_URL, file_name="tiny.png", scope="test")

    provider.generate(ModelRequest(
        messages=[{"role": "user", "content": "What is this?", "attachments": [artifact.to_dict()]}],
        request_options={
            "_write_note_media_store": media_store,
            "_paper_notes_session_id": "session-1",
        },
    ))

    payload = client.responses.calls[0]
    assert "_write_note_media_store" not in payload
    content = payload["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "What is this?"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")


def test_openai_provider_rejects_image_attachments_for_non_vision_model(tmp_path):
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Done", usage=None)
    client = FakeClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-5.3-codex-spark")
    media_store = MediaStore(tmp_path / ".paper-notes" / "media")
    artifact = media_store.create_upload(PNG_DATA_URL, file_name="tiny.png", scope="test")

    with pytest.raises(ModelProviderConfigError) as exc_info:
        provider.generate(ModelRequest(
            messages=[{"role": "user", "content": "What is this?", "attachments": [artifact.to_dict()]}],
            request_options={
                "_write_note_media_store": media_store,
                "_paper_notes_provider": "codex-oauth",
            },
        ))

    assert client.responses.calls == []
    assert "gpt-5.3-codex-spark" in str(exc_info.value)
    assert "supports image input" in str(exc_info.value)


def test_openai_provider_classifies_upstream_image_input_rejection():
    client = ImageInputUnsupportedClient()
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")

    with pytest.raises(ModelProviderAPIError) as exc_info:
        provider.generate(ModelRequest(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Analyze this."},
                    {"type": "input_image", "image_url": PNG_DATA_URL},
                ],
            }],
        ))

    assert client.responses.calls
    assert exc_info.value.provider_data["code"] == "image_input_unavailable"
    assert "vision-capable model" in str(exc_info.value)
    assert "platform.openai.com" not in str(exc_info.value)


def test_openai_provider_maps_file_attachments_to_text_input(tmp_path):
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Done", usage=None)
    client = FakeClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")
    media_store = MediaStore(tmp_path / ".paper-notes" / "media")
    artifact = media_store.create_upload("data:text/markdown;base64,IyBOb3RlcwoKSGVsbG8=", file_name="notes.md", scope="test")

    provider.generate(ModelRequest(
        messages=[{"role": "user", "content": "Summarize this.", "attachments": [artifact.to_dict()]}],
        request_options={
            "_write_note_media_store": media_store,
            "_paper_notes_session_id": "session-1",
        },
    ))

    content = client.responses.calls[0]["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "Summarize this."}
    assert content[1]["type"] == "input_text"
    assert "Attachment: notes.md" in content[1]["text"]
    assert "# Notes" in content[1]["text"]


def test_openai_provider_maps_code_attachments_to_text_input(tmp_path):
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Done", usage=None)
    client = FakeClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")
    media_store = MediaStore(tmp_path / ".paper-notes" / "media")
    artifact = media_store.create_upload("data:application/octet-stream;base64,Y29uc29sZS5sb2coJ2hpJyk7Cg==", file_name="script.js", scope="test")

    provider.generate(ModelRequest(
        messages=[{"role": "user", "content": "Summarize this.", "attachments": [artifact.to_dict()]}],
        request_options={
            "_write_note_media_store": media_store,
            "_paper_notes_session_id": "session-1",
        },
    ))

    content = client.responses.calls[0]["input"][0]["content"]
    assert content[1]["type"] == "input_text"
    assert "Attachment: script.js" in content[1]["text"]
    assert "console.log('hi');" in content[1]["text"]


def test_openai_provider_retries_image_request_with_shrunken_payload():
    response = SimpleNamespace(id="resp_1", status="completed", output=[], output_text="Done", usage=None)
    client = FlakyImageClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-test")
    image_url = _noisy_jpeg_data_url()

    result = provider.generate(ModelRequest(
        messages=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Analyze this."},
                {"type": "input_image", "image_url": image_url},
            ],
        }],
        request_options={"_paper_notes_image_retry_target_bytes": 50_000},
    ))

    first_url = client.responses.calls[0]["input"][0]["content"][1]["image_url"]
    second_url = client.responses.calls[1]["input"][0]["content"][1]["image_url"]
    assert result.content == "Done"
    assert first_url == image_url
    assert len(second_url) < len(first_url)


def test_openai_provider_preserves_image_generation_tool_and_saves_artifact(tmp_path):
    response = SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[
            SimpleNamespace(
                type="image_generation_call",
                id="ig_1",
                result=PNG_DATA_URL.removeprefix("data:image/png;base64,"),
                revised_prompt="A tiny image.",
            ),
        ],
        output_text="",
        usage=None,
    )
    client = FakeClient(response)
    provider = OpenAIModelProvider(client=client, default_model="gpt-image")
    media_store = MediaStore(tmp_path / ".paper-notes" / "media")

    result = provider.generate(ModelRequest(
        messages=[{"role": "user", "content": "Generate an image"}],
        tools=[{"type": "image_generation", "size": "1024x1024"}],
        request_options={
            "_write_note_media_store": media_store,
            "_paper_notes_session_id": "session-1",
            "_paper_notes_provider": "openai",
            "_paper_notes_image_generation": {"enabled": True, "format": "png"},
        },
    ))

    assert client.responses.calls[0]["tools"] == [{"type": "image_generation", "size": "1024x1024"}]
    assert len(result.artifacts) == 1
    assert result.artifacts[0]["source"] == "generated"
    assert result.artifacts[0]["url"].startswith("/api/media/")
    assert media_store.path_for(result.artifacts[0]["id"]).exists()


def test_openai_provider_normalizes_codex_replay_metadata_from_response():
    response = SimpleNamespace(
        id="resp_1",
        status="incomplete",
        output=[
            SimpleNamespace(
                type="reasoning",
                id="rs_1",
                encrypted_content="opaque",
                summary=[SimpleNamespace(text="thinking")],
            ),
            SimpleNamespace(
                type="message",
                id="msg_1",
                role="assistant",
                status="incomplete",
                phase="commentary",
                content=[SimpleNamespace(type="output_text", text="Working")],
            ),
        ],
        output_text="",
        incomplete_details=SimpleNamespace(reason="reasoning"),
        usage=None,
    )
    provider = OpenAIModelProvider(client=FakeClient(response), default_model="gpt-test")

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Continue"}]))

    assert result.finish_reason == "incomplete"
    assert result.provider_data["incomplete_reason"] == "reasoning"
    assert result.provider_data["codex_reasoning_items"][0]["encrypted_content"] == "opaque"
    assert result.provider_data["codex_message_items"][0]["phase"] == "commentary"
    assert result.provider_data["work_trace_items"] == [
        {"type": "summary", "text": "thinking", "source": "provider"},
        {"type": "commentary", "text": "Working", "source": "provider"},
    ]


def test_openai_provider_treats_leaked_tool_call_text_as_incomplete():
    response = SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                id="msg_1",
                role="assistant",
                status="completed",
                content=[SimpleNamespace(type="output_text", text='assistant to=functions.search_notes {"query":"x"}')],
            ),
        ],
        output_text='assistant to=functions.search_notes {"query":"x"}',
        usage=None,
    )
    provider = OpenAIModelProvider(client=FakeClient(response), default_model="gpt-test")

    result = provider.generate(ModelRequest(messages=[{"role": "user", "content": "Search"}]))

    assert result.finish_reason == "incomplete"
    assert result.content is None
    assert result.provider_data["leaked_tool_call_text"] is True


def test_openai_provider_requires_api_key_without_client(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("PAPER_NOTES_SECRETS_PATH", str(tmp_path / "secrets.env"))
    monkeypatch.setenv("PAPER_NOTES_ENV_PATHS", str(tmp_path / "missing.env"))

    with pytest.raises(ModelProviderConfigError):
        OpenAIModelProvider()


def test_openai_provider_preserves_api_error_status_and_body():
    provider = OpenAIModelProvider(client=RaisingClient(), default_model="gpt-test")

    with pytest.raises(ModelProviderAPIError) as exc_info:
        provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))

    assert exc_info.value.status_code == 400
    assert exc_info.value.body == {"error": "too many tokens"}


def test_openai_provider_preserves_api_error_code_metadata():
    provider = OpenAIModelProvider(client=QuotaRaisingClient(), default_model="gpt-test")

    with pytest.raises(ModelProviderAPIError) as exc_info:
        provider.generate(ModelRequest(messages=[{"role": "user", "content": "Hi"}]))

    assert exc_info.value.status_code == 429
    assert exc_info.value.provider_data["api_error_code"] == "insufficient_quota"
    assert exc_info.value.provider_data["api_error_type"] == "insufficient_quota"


def _noisy_jpeg_data_url() -> str:
    from PIL import Image

    width = 512
    height = 512
    data = bytes((index * 37) % 256 for index in range(width * height * 3))
    image = Image.frombytes("RGB", (width, height), data)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"
