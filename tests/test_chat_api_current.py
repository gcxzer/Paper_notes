from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agent_runtime import AgentService
from agent_sessions import AgentSessionStore
from app_config import AppConfig
from media import MediaStore
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


def _client(monkeypatch, tmp_path, responses: list[AIMessage] | None = None) -> tuple[TestClient, AgentService]:
    service = AgentService(
        app_config=_config(),
        session_store=AgentSessionStore(tmp_path / "sessions"),
        chat_model=FakeMessagesListChatModel(responses=responses or [AIMessage(content="Chat response.")]),
        use_default_tools=False,
    )
    monkeypatch.setattr(agent_api, "_AGENT_SERVICE", service)
    monkeypatch.setattr(chat_api, "_MEDIA_STORE", MediaStore(tmp_path / "media"))
    return TestClient(create_app()), service


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
