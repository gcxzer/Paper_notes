from __future__ import annotations

from fastapi.testclient import TestClient

from ui.backend import server
from ui.backend.server import create_app


def test_open_local_file_requires_trusted_header(tmp_path):
    target = tmp_path / "paper.pdf"
    target.write_text("pdf", encoding="utf-8")

    response = TestClient(create_app()).post("/api/open-local-file", json={"path": str(target)})

    assert response.status_code == 403
    assert response.json()["code"] == "missing_local_action_header"


def test_open_local_file_opens_existing_absolute_path(monkeypatch, tmp_path):
    target = tmp_path / "supplement.txt"
    target.write_text("data", encoding="utf-8")
    calls: list[list[str]] = []

    monkeypatch.setattr(server.sys, "platform", "darwin")
    monkeypatch.setattr(server.subprocess, "Popen", lambda args: calls.append(args))

    response = TestClient(create_app()).post(
        "/api/open-local-file",
        headers={"X-Paper-Notes-Local-Action": "open-local-file"},
        json={"path": str(target)},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "path": str(target.resolve())}
    assert calls == [["open", str(target.resolve())]]


def test_open_local_file_rejects_web_urls():
    response = TestClient(create_app()).post(
        "/api/open-local-file",
        headers={"X-Paper-Notes-Local-Action": "open-local-file"},
        json={"href": "https://example.com/file.pdf"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "unsupported_scheme"
