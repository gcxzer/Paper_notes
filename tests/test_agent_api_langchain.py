from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agent_runtime import AgentService, AgentServiceRequest
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


def test_agent_session_routes_manage_sessions(monkeypatch, tmp_path):
    client, service = _client(monkeypatch, tmp_path)
    created = service.run(AgentServiceRequest(message="Hello", title="Original", enable_tools=False))
    session_id = created.session_id

    listed = client.get("/api/agent/sessions").json()
    assert [session["sessionId"] for session in listed["sessions"]] == [session_id]

    loaded = client.get(f"/api/agent/sessions/{session_id}").json()
    assert loaded["session"]["id"] == session_id
    assert loaded["session"]["title"] == "Original"
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


def test_agent_session_model_route_updates_model_and_metadata(monkeypatch, tmp_path):
    client, service = _client(monkeypatch, tmp_path)
    created = service.run(AgentServiceRequest(message="Hello", enable_tools=False))
    session_id = created.session_id

    response = client.post(
        f"/api/agent/sessions/{session_id}/model",
        json={
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "metadata": {"deepseekThinkMode": "off"},
        },
    )

    assert response.status_code == 200
    session = response.json()["session"]
    assert session["id"] == session_id
    assert session["provider"] == "deepseek"
    assert session["model"] == "deepseek-v4-flash"
    assert session["deepseekThinkMode"] == "off"


def test_agent_session_routes_return_404_for_missing_session(monkeypatch, tmp_path):
    client, _service = _client(monkeypatch, tmp_path)

    assert client.get("/api/agent/sessions/missing").status_code == 404
