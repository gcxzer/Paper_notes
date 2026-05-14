from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from media import MediaStore
from model_providers.codex.types import CodexCredentials
from tools.generated_images import API_IMAGE_MODEL, TOOL_NAME, register_generated_image_tool
from tools.registry import ToolRegistry


PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
PNG_DATA_URL = f"data:image/png;base64,{PNG_B64}"


class FakeAuthStore:
    def __init__(self, credentials: CodexCredentials) -> None:
        self.credentials = credentials

    def runtime_credentials(self) -> CodexCredentials:
        return self.credentials


class FakeCodexStream:
    def __init__(self, events: list[SimpleNamespace], final_response: SimpleNamespace | None = None) -> None:
        self.events = events
        self.final_response = final_response or SimpleNamespace(output=[])

    def __enter__(self) -> "FakeCodexStream":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def __iter__(self):
        return iter(self.events)

    def get_final_response(self) -> SimpleNamespace:
        return self.final_response


class FakeCodexResponses:
    def __init__(self, stream: FakeCodexStream) -> None:
        self.stream_result = stream
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return self.stream_result


class FakeCodexClient:
    def __init__(self, stream: FakeCodexStream) -> None:
        self.responses = FakeCodexResponses(stream)


class FakeOpenAIImages:
    def __init__(self) -> None:
        self.generate_calls: list[dict] = []
        self.edit_calls: list[dict] = []

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=PNG_B64)])

    def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=PNG_B64)])


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.images = FakeOpenAIImages()


def test_codex_image_tool_requires_auth(tmp_path):
    registry = ToolRegistry()
    store = MediaStore(tmp_path / ".paper-notes" / "media")
    register_generated_image_tool(
        registry,
        media_store=store,
        provider_name_provider=lambda: "codex-oauth",
        model_provider=lambda: "gpt-5.5",
        codex_auth_store=FakeAuthStore(CodexCredentials()),
    )

    result = registry.dispatch(TOOL_NAME, {"prompt": "make an image"})

    assert result.is_error is True
    assert "codex_auth_required" in result.content


def test_codex_image_tool_uses_current_host_model_and_required_image_tool(tmp_path):
    stream = FakeCodexStream([
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(type="image_generation_call", result=PNG_B64),
        )
    ])
    client = FakeCodexClient(stream)
    registry = ToolRegistry()
    store = MediaStore(tmp_path / ".paper-notes" / "media")
    register_generated_image_tool(
        registry,
        media_store=store,
        session_id_provider=lambda: "session-1",
        provider_name_provider=lambda: "codex-oauth",
        model_provider=lambda: "gpt-5.5",
        image_generation_provider=lambda: {"enabled": True, "size": "1536x1024", "quality": "medium"},
        codex_auth_store=FakeAuthStore(CodexCredentials(access_token="token")),
        codex_client_factory=lambda credentials: client,
    )

    result = registry.dispatch(TOOL_NAME, {"prompt": "make an image"})

    assert result.is_error is False
    payload = json.loads(result.content)
    assert payload["artifact"]["kind"] == "image"
    call = client.responses.calls[0]
    assert call["model"] == "gpt-5.5"
    assert call["tools"][0]["type"] == "image_generation"
    assert call["tools"][0]["model"] == API_IMAGE_MODEL
    assert call["tools"][0]["size"] == "1536x1024"
    assert call["tools"][0]["quality"] == "medium"
    assert call["tool_choice"]["mode"] == "required"
    assert "action" not in call["tools"][0]


def test_codex_image_tool_accepts_partial_and_final_response_paths(tmp_path):
    for event_b64, final_b64 in [(PNG_B64, ""), ("", PNG_B64)]:
        events = []
        final = SimpleNamespace(output=[])
        if event_b64:
            events.append(SimpleNamespace(type="response.image_generation_call.partial_image", partial_image_b64=event_b64))
        if final_b64:
            final = SimpleNamespace(output=[SimpleNamespace(type="image_generation_call", result=final_b64)])
        client = FakeCodexClient(FakeCodexStream(events, final))
        registry = ToolRegistry()
        store = MediaStore(tmp_path / ".paper-notes" / f"media-{len(events)}-{bool(final_b64)}")
        register_generated_image_tool(
            registry,
            media_store=store,
            session_id_provider=lambda: "session-1",
            provider_name_provider=lambda: "codex-oauth",
            model_provider=lambda: "gpt-5.4",
            codex_auth_store=FakeAuthStore(CodexCredentials(access_token="token")),
            codex_client_factory=lambda credentials, client=client: client,
        )

        result = registry.dispatch(TOOL_NAME, {"prompt": "make an image"})

        assert result.is_error is False
        assert json.loads(result.content)["artifact"]["mimeType"] == "image/png"


def test_codex_image_tool_sends_image_attachments_as_inputs(tmp_path):
    client = FakeCodexClient(FakeCodexStream([
        SimpleNamespace(type="response.output_item.done", item=SimpleNamespace(type="image_generation_call", result=PNG_B64))
    ]))
    registry = ToolRegistry()
    store = MediaStore(tmp_path / ".paper-notes" / "media")
    upload = store.create_upload(PNG_DATA_URL, file_name="source.png", scope="session-1")
    register_generated_image_tool(
        registry,
        media_store=store,
        provider_name_provider=lambda: "codex-oauth",
        model_provider=lambda: "gpt-5.5",
        attachment_provider=lambda: [upload.to_dict()],
        codex_auth_store=FakeAuthStore(CodexCredentials(access_token="token")),
        codex_client_factory=lambda credentials: client,
    )

    result = registry.dispatch(TOOL_NAME, {"prompt": "edit this image", "mode": "edit"})

    assert result.is_error is False
    content = client.responses.calls[0]["input"][0]["content"]
    assert any(item.get("type") == "input_image" and item.get("image_url", "").startswith("data:image/png;base64,") for item in content)


def test_openai_image_tool_generate_and_edit(tmp_path):
    client = FakeOpenAIClient()
    registry = ToolRegistry()
    store = MediaStore(tmp_path / ".paper-notes" / "media")
    upload = store.create_upload(PNG_DATA_URL, file_name="source.png", scope="session-1")
    register_generated_image_tool(
        registry,
        media_store=store,
        session_id_provider=lambda: "session-1",
        provider_name_provider=lambda: "openai",
        model_provider=lambda: "gpt-5.5",
        openai_client_factory=lambda: client,
    )

    generated = registry.dispatch(TOOL_NAME, {"prompt": "make an image"})
    edited = registry.dispatch(TOOL_NAME, {
        "prompt": "edit this image",
        "mode": "edit",
        "input_artifact_ids": [upload.id],
    })

    assert generated.is_error is False
    assert edited.is_error is False
    assert client.images.generate_calls[0]["model"] == API_IMAGE_MODEL
    assert client.images.edit_calls[0]["model"] == API_IMAGE_MODEL
    assert client.images.edit_calls[0]["image"]


def test_openai_image_tool_default_client_uses_resolved_api_key(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class FakeDefaultOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.images = FakeOpenAIImages()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeDefaultOpenAI))
    registry = ToolRegistry()
    store = MediaStore(tmp_path / ".paper-notes" / "media")
    register_generated_image_tool(
        registry,
        media_store=store,
        session_id_provider=lambda: "session-1",
        provider_name_provider=lambda: "openai",
        model_provider=lambda: "gpt-5.5",
    )

    result = registry.dispatch(TOOL_NAME, {"prompt": "make an image"})

    assert result.is_error is False
    assert captured["api_key"] == "sk-test-secret"
