from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel, FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from agent_runtime import AgentService
from agent_sessions import AgentSessionStore
from app_config import AppConfig
from media import MediaStore
from model_providers import ModelProviderConfig
from ui.backend import agent_api, chat_api
from ui.backend.server import create_app


def _config() -> AppConfig:
    return AppConfig(
        data={
            "models": {
                "default": "main",
                "main": {
                    "provider": "openai",
                    "name": "gpt-5.5",
                    "options": {},
                },
            },
        },
        path=None,
    )


def _client(monkeypatch, tmp_path, responses: list[AIMessage] | None = None, chat_model: Any | None = None) -> tuple[TestClient, AgentService]:
    service = AgentService(
        app_config=_config(),
        session_store=AgentSessionStore(tmp_path / "sessions"),
        chat_model=chat_model or FakeMessagesListChatModel(responses=responses or [AIMessage(content="Chat response.")]),
        use_default_tools=False,
    )
    monkeypatch.setattr(agent_api, "_AGENT_SERVICE", service)
    monkeypatch.setattr(chat_api, "_MEDIA_STORE", MediaStore(tmp_path / "media"))
    return TestClient(create_app()), service


def test_app_registers_chat_context_routes(monkeypatch, tmp_path):
    client, _service = _client(monkeypatch, tmp_path)

    paths = {route.path: getattr(route, "methods", set()) for route in client.app.routes}

    assert "GET" in paths["/api/chat/context"]
    assert "POST" in paths["/api/chat/compress"]


def test_chat_endpoint_runs_current_agent_service(monkeypatch, tmp_path):
    client, service = _client(monkeypatch, tmp_path)

    response = client.post("/api/chat", json={"message": "Hello", "requestId": "req-1", "enableTools": False})

    assert response.status_code == 200
    payload = response.json()
    assert payload["requestId"] == "req-1"
    assert payload["completed"] is True
    assert payload["response"] == "Chat response."
    assert payload["messages"][-1]["text"] == "Chat response."
    assert service.session_store.require_session(payload["sessionId"]).metadata.message_count == 2


def test_chat_stream_endpoint_emits_start_final_and_done(monkeypatch, tmp_path):
    client, _service = _client(monkeypatch, tmp_path)

    with client.stream("POST", "/api/chat/stream", json={"message": "Hello", "requestId": "req-stream", "enableTools": False}) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert "event: start" in body
    assert "event: final" in body
    assert "event: done" in body
    assert "Chat response." in body
    assert "req-stream" in body


def test_chat_stream_endpoint_emits_model_deltas_before_final(monkeypatch, tmp_path):
    client, _service = _client(monkeypatch, tmp_path, chat_model=FakeListChatModel(responses=["Typed response."]))

    with client.stream("POST", "/api/chat/stream", json={"message": "Hello", "requestId": "req-delta", "enableTools": False}) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert "event: model_delta" in body
    assert body.index("event: model_delta") < body.index("event: final")
    assert '"delta":"T"' in body
    assert "Typed response." in body
    assert '"runTrace"' in body
    assert '"status":"completed"' in body


def test_chat_request_options_are_forwarded_to_model_config(monkeypatch, tmp_path):
    captured: list[ModelProviderConfig] = []

    def model_factory(config: AppConfig) -> FakeMessagesListChatModel:
        captured.append(ModelProviderConfig.from_app_config(config))
        return FakeMessagesListChatModel(responses=[AIMessage(content="Options response.")])

    service = AgentService(
        app_config=_config(),
        session_store=AgentSessionStore(tmp_path / "sessions"),
        model_factory=model_factory,
        use_default_tools=False,
    )
    monkeypatch.setattr(agent_api, "_AGENT_SERVICE", service)
    monkeypatch.setattr(chat_api, "_MEDIA_STORE", MediaStore(tmp_path / "media"))
    client = TestClient(create_app())

    response = client.post(
        "/api/chat",
        json={
            "message": "Hello",
            "enableTools": False,
            "requestOptions": {
                "reasoning": {"effort": "high", "summary": "auto"},
                "temperature": 0,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["response"] == "Options response."
    assert captured[0].options["reasoning"] == {"effort": "high", "summary": "auto"}
    assert captured[0].options["temperature"] == 0


def test_chat_image_generation_options_and_artifacts_are_forwarded(monkeypatch, tmp_path):
    captured: list[ModelProviderConfig] = []
    artifact = {
        "id": "gen_1",
        "kind": "image",
        "source": "generated",
        "mimeType": "image/png",
        "fileName": "gen_1.png",
        "url": "/api/media/gen_1",
        "downloadUrl": "/api/media/gen_1/download",
    }

    def model_factory(config: AppConfig) -> FakeMessagesListChatModel:
        captured.append(ModelProviderConfig.from_app_config(config))
        return FakeMessagesListChatModel(responses=[AIMessage(content="", response_metadata={"artifacts": [artifact]})])

    service = AgentService(
        app_config=_config(),
        session_store=AgentSessionStore(tmp_path / "sessions"),
        model_factory=model_factory,
        use_default_tools=False,
    )
    monkeypatch.setattr(agent_api, "_AGENT_SERVICE", service)
    monkeypatch.setattr(chat_api, "_MEDIA_STORE", MediaStore(tmp_path / "media"))
    client = TestClient(create_app())

    response = client.post(
        "/api/chat",
        json={
            "message": "Generate an image",
            "enableTools": False,
            "imageGeneration": {"enabled": True, "size": "1024x1024", "quality": "auto", "format": "png"},
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["artifacts"] == [artifact]
    assert payload["messages"][-1]["artifacts"] == [artifact]
    assert captured[0].options["_paper_notes_image_generation"]["size"] == "1024x1024"
    assert captured[0].options["_paper_notes_session_id"] == payload["sessionId"]
    assert captured[0].options["_write_note_media_store"] is not None


def test_chat_context_status_prefers_actual_usage_tokens(monkeypatch, tmp_path):
    client, _service = _client(
        monkeypatch,
        tmp_path,
        responses=[
            AIMessage(
                content="Usage response.",
                usage_metadata={"input_tokens": 420_000, "output_tokens": 100, "total_tokens": 420_100},
            )
        ],
    )
    chat = client.post("/api/chat", json={"message": "Hello", "enableTools": False})
    session_id = chat.json()["sessionId"]

    response = client.get(f"/api/chat/context?sessionId={session_id}&enableTools=false")

    assert response.status_code == 200
    context = response.json()["context"]
    assert context["actualUsageAvailable"] is True
    assert context["actualInputTokens"] == 420_000
    assert context["actualOutputTokens"] == 100
    assert context["actualTotalTokens"] == 420_100
    assert context["tokensUsed"] == 420_000
    assert context["percentFull"] == 40
    assert context["estimatedRequestTokens"] > 0


def test_chat_system_prompt_uses_agent_instructions_for_current_note():
    prompt = chat_api._system_prompt({
        "noteId": "pdf-deepseek-v4-mqcvdnpd",
        "noteTitle": "DeepSeek V4",
        "currentPage": 1,
    })

    assert "You are Paper Notes Agent" in prompt
    assert "No Paper Notes retrieval tools are currently available" in prompt
    assert "# Current Reading Context" in prompt
    assert "id: pdf-deepseek-v4-mqcvdnpd" in prompt
    assert "title: DeepSeek V4" in prompt
    assert "Current page: 1" in prompt


def test_prepare_chat_run_system_prompt_includes_enabled_tool_guidance(tmp_path):
    def _read_paper(note_id: str) -> str:
        return f"paper text for {note_id}"

    tool = StructuredTool.from_function(
        func=_read_paper,
        name="read_paper",
        description="Read paper text.",
    )
    service = AgentService(
        app_config=_config(),
        session_store=AgentSessionStore(tmp_path / "sessions"),
        chat_model=FakeMessagesListChatModel(responses=[AIMessage(content="Chat response.")]),
        tools=[tool],
        use_default_tools=False,
    )

    _agent_service, request, _attachments, _visible_text = chat_api._prepare_chat_run(
        {
            "message": "这篇论文说了啥",
            "noteId": "pdf-deepseek-v4-mqcvdnpd",
            "noteTitle": "DeepSeek V4",
            "enableTools": True,
        },
        service=service,
        media_store=MediaStore(tmp_path / "media"),
    )

    assert request.system_prompt is not None
    assert "# Tool use and grounding" in request.system_prompt
    assert "Available local tools:" in request.system_prompt
    assert "read_paper" in request.system_prompt
    assert "id: pdf-deepseek-v4-mqcvdnpd" in request.system_prompt


def test_chat_attachment_upload_serves_media_and_persists_on_user_message(monkeypatch, tmp_path):
    client, service = _client(monkeypatch, tmp_path)
    uploaded = client.post(
        "/api/chat/attachments",
        json={
            "data": "data:text/plain;base64,SGVsbG8gZmlsZQ==",
            "fileName": "notes.txt",
            "mimeType": "text/plain",
            "requestId": "upload-1",
        },
    )

    assert uploaded.status_code == 201
    artifact = uploaded.json()["artifact"]
    assert artifact["kind"] == "text"
    assert artifact["fileName"] == "notes.txt"
    assert client.get(artifact["url"]).content == b"Hello file"

    chat = client.post(
        "/api/chat",
        json={
            "message": "Summarize this.",
            "attachments": [{"id": artifact["id"]}],
            "enableTools": False,
        },
    ).json()
    session = service.session_store.require_session(chat["sessionId"])
    user_message = next(message for message in session.messages if message["role"] == "user")

    assert user_message["attachments"][0]["id"] == artifact["id"]
    assert "Hello file" in str(user_message["content"])


def test_chat_context_and_compress_routes(monkeypatch, tmp_path):
    client, service = _client(
        monkeypatch,
        tmp_path,
        chat_model=FakeMessagesListChatModel(responses=[AIMessage(content="dense summary")]),
    )
    session = service.session_store.create_session(title="Compact route")
    service.session_store.replace_messages(session.metadata.session_id, [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "current question"},
    ])

    context = client.get(f"/api/chat/context?sessionId={session.metadata.session_id}&model=gpt-5.5")

    assert context.status_code == 200
    assert context.json()["context"]["compactionEnabled"] is True
    assert context.json()["context"]["messageCount"] == 5

    compact = client.post(
        "/api/chat/compress",
        json={"sessionId": session.metadata.session_id, "enableTools": False},
    )

    assert compact.status_code == 200
    payload = compact.json()
    assert payload["compressed"] is True
    assert payload["message"]["role"] == "divider"
    assert payload["message"]["markerType"] == "context_compaction_marker"
    assert payload["context"]["summaryAvailable"] is True
    assert payload["context"]["compressionCount"] == 1
