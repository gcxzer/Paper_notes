from __future__ import annotations

import importlib
from dataclasses import dataclass

from fastapi.testclient import TestClient

from ui.backend import server
from ui.backend.server import content_disposition_attachment, create_app, _sse_frame


def client() -> TestClient:
    return TestClient(create_app())


def test_content_disposition_attachment_supports_unicode_file_names():
    header = content_disposition_attachment("朱旋-阅读3-课前打卡.pdf")

    assert header.encode("latin-1")
    assert 'filename*=' in header
    assert "%E6%9C%B1%E6%97%8B-%E9%98%85%E8%AF%BB3-" in header


def test_fastapi_serves_index_with_compat_headers():
    response = client().get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert b"Paper Notes" in response.content
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET,HEAD,POST,DELETE,OPTIONS"
    assert response.headers["access-control-allow-headers"] == "Content-Type, X-Paper-Notes-Local-Action"
    assert response.headers["cache-control"] == "no-store"


def test_fastapi_serves_static_assets_and_notes_json():
    app_client = client()

    script_response = app_client.get("/assets/scripts/site/library.js")
    notes_response = app_client.get("/notes.json")

    assert script_response.status_code == 200
    assert script_response.headers["content-type"].startswith("text/javascript")
    assert b"fetchJson" in script_response.content
    assert notes_response.status_code == 200
    assert notes_response.headers["content-type"].startswith("application/json")


def test_fastapi_static_blocks_paths_outside_frontend_root():
    response = client().get("/%2E%2E/pyproject.toml")

    assert response.status_code == 403
    assert response.text == "Forbidden"


def test_fastapi_static_returns_not_found_and_head_has_no_body():
    app_client = client()

    missing_response = app_client.get("/missing-static-file.txt")
    head_response = app_client.head("/")

    assert missing_response.status_code == 404
    assert missing_response.text == "Not found"
    assert head_response.status_code == 200
    assert head_response.content == b""


def test_fastapi_options_returns_no_content():
    response = client().options("/api/library")

    assert response.status_code == 204
    assert response.content == b""


def test_fastapi_get_library_route(monkeypatch):
    monkeypatch.setattr(server, "read_library", lambda: {"categories": [], "notes": []})

    response = client().get("/api/library")

    assert response.status_code == 200
    assert response.json() == {"categories": [], "notes": []}


def test_fastapi_rename_note_missing_payload_returns_400():
    response = client().post("/api/rename-note", json={})

    assert response.status_code == 400
    assert response.text == "Note id and title are required."


def test_fastapi_delete_ai_key_uses_query_provider(monkeypatch):
    calls = []

    def fake_delete_ai_api_key(provider: str):
        calls.append(provider)
        return {"provider": provider, "deleted": True}

    monkeypatch.setattr(server, "delete_ai_api_key", fake_delete_ai_api_key)

    response = client().delete("/api/settings/ai/key?provider=deepseek")

    assert response.status_code == 200
    assert response.json() == {"provider": "deepseek", "deleted": True}
    assert calls == ["deepseek"]


@dataclass
class FakeArtifact:
    id: str
    mime_type: str
    file_name: str


class FakeMediaStore:
    def require_artifact(self, artifact_id: str) -> FakeArtifact:
        assert artifact_id == "artifact-1"
        return FakeArtifact(id=artifact_id, mime_type="image/png", file_name="朱旋 image.png")

    def read_bytes(self, artifact_id: str) -> bytes:
        assert artifact_id == "artifact-1"
        return b"png-bytes"


class FakeAgentService:
    media_store = FakeMediaStore()


def test_fastapi_media_download_uses_artifact_headers(monkeypatch):
    monkeypatch.setattr(server, "get_agent_service", lambda: FakeAgentService())

    response = client().get("/api/media/artifact-1/download")

    assert response.status_code == 200
    assert response.content == b"png-bytes"
    assert response.headers["content-type"].startswith("image/png")
    assert 'filename*=' in response.headers["content-disposition"]
    assert "%E6%9C%B1%E6%97%8B%20image.png" in response.headers["content-disposition"]


def test_fastapi_chat_stream_preserves_sse_frame_format(monkeypatch):
    def fake_handle_chat_stream_request(body, *, send_event, **kwargs):
        send_event("start", {"requestId": body["requestId"]})
        send_event("final", {"response": "Hello"})
        send_event("done", {})

    monkeypatch.setattr(server, "handle_chat_stream_request", fake_handle_chat_stream_request)

    response = client().post("/api/chat/stream", json={"requestId": "req-1"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert response.content == (
        _sse_frame("start", {"requestId": "req-1"})
        + _sse_frame("final", {"response": "Hello"})
        + _sse_frame("done", {})
    )


def test_paths_host_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("HOST", raising=False)

    import app_infra.paths as paths

    try:
        importlib.reload(paths)
        assert paths.HOST == "127.0.0.1"
    finally:
        importlib.reload(paths)


def test_paths_host_can_be_overridden(monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")

    import app_infra.paths as paths

    try:
        importlib.reload(paths)
        assert paths.HOST == "0.0.0.0"
    finally:
        monkeypatch.delenv("HOST", raising=False)
        importlib.reload(paths)
