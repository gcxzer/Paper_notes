from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agent_runtime import AgentService
from agent_sessions import AgentSessionStore
from app_config import AppConfig
from ui.backend import agent_api
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
        chat_model=FakeMessagesListChatModel(responses=responses or [AIMessage(content="API response.")]),
        use_default_tools=False,
    )
    monkeypatch.setattr(agent_api, "_AGENT_SERVICE", service)
    return TestClient(create_app()), service


def test_agent_run_endpoint_creates_session_and_returns_response(monkeypatch, tmp_path):
    client, service = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/agent/run",
        json={"message": "Hello", "title": "API chat", "enableTools": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["createdSession"] is True
    assert payload["response"] == "API response."
    assert payload["session"]["metadata"]["title"] == "API chat"
    assert [message["content"] for message in payload["messages"]] == ["Hello", "API response."]
    assert service.session_store.require_session(payload["sessionId"]).metadata.message_count == 2


def test_agent_run_endpoint_continues_session(monkeypatch, tmp_path):
    client, _service = _client(
        monkeypatch,
        tmp_path,
        responses=[
            AIMessage(content="First response."),
            AIMessage(content="Second response."),
        ],
    )
    first = client.post("/api/agent/run", json={"message": "First", "enableTools": False}).json()

    response = client.post(
        "/api/agent/run",
        json={"message": "Second", "sessionId": first["sessionId"], "enableTools": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["createdSession"] is False
    assert [message["content"] for message in payload["messages"]] == [
        "First",
        "First response.",
        "Second",
        "Second response.",
    ]


def test_agent_session_routes_manage_sessions(monkeypatch, tmp_path):
    client, _service = _client(monkeypatch, tmp_path)
    created = client.post("/api/agent/run", json={"message": "Hello", "title": "Original", "enableTools": False}).json()
    session_id = created["sessionId"]

    listed = client.get("/api/agent/sessions").json()
    assert [session["sessionId"] for session in listed["sessions"]] == [session_id]

    loaded = client.get(f"/api/agent/sessions/{session_id}").json()
    assert loaded["session"]["metadata"]["title"] == "Original"
    assert loaded["session"]["messages"][0]["content"] == "Hello"

    renamed = client.post(f"/api/agent/sessions/{session_id}/rename", json={"title": "Renamed"}).json()
    assert renamed["session"]["title"] == "Renamed"

    archived = client.post(f"/api/agent/sessions/{session_id}/archive", json={"archived": True}).json()
    assert archived["session"]["state"] == "archived"
    assert client.get("/api/agent/sessions").json()["sessions"] == []
    assert client.get("/api/agent/sessions", params={"includeArchived": True}).json()["sessions"][0]["sessionId"] == session_id

    restored = client.post(f"/api/agent/sessions/{session_id}/state", json={"state": "active"}).json()
    assert restored["session"]["state"] == "active"

    deleted = client.delete(f"/api/agent/sessions/{session_id}").json()
    assert deleted["deletedSession"]["sessionId"] == session_id
    assert client.get(f"/api/agent/sessions/{session_id}").status_code == 404


def test_agent_context_status_endpoint(monkeypatch, tmp_path):
    client, _service = _client(monkeypatch, tmp_path)
    created = client.post("/api/agent/run", json={"message": "Hello", "enableTools": False}).json()

    response = client.get(f"/api/agent/sessions/{created['sessionId']}/context", params={"enableTools": False})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    context = payload["context"]
    assert context["sessionId"] == created["sessionId"]
    assert context["provider"] == "openai"
    assert context["model"] == "gpt-5.5"
    assert context["contextWindow"] == 1_050_000
    assert context["reserveTokens"] == 20_000
    assert context["collapseTriggerTokens"] == 1_030_000
    assert context["remainingTokens"] == context["contextWindow"] - context["estimatedTokens"]


def test_agent_session_routes_return_404_for_missing_session(monkeypatch, tmp_path):
    client, _service = _client(monkeypatch, tmp_path)

    assert client.get("/api/agent/sessions/missing").status_code == 404
    assert client.get("/api/agent/sessions/missing/context").status_code == 404
    assert client.post("/api/agent/run", json={"message": "Hello", "sessionId": "missing"}).status_code == 404
