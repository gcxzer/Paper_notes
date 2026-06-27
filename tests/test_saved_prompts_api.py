from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ui.backend import saved_prompts_api
from ui.backend.saved_prompts_api import normalize_saved_prompts, read_saved_prompts, write_saved_prompts
from ui.backend.server import create_app


def test_saved_prompts_round_trip(tmp_path):
    path = tmp_path / ".paper-notes" / "saved-prompts.json"

    payload = write_saved_prompts(
        {
            "prompts": [{
                "id": "prompt-1",
                "title": "Summarize",
                "content": "Summarize this paper.",
                "toolMode": "file",
                "fileFormat": "markdown",
                "iconType": "icon",
                "iconValue": "file",
                "createdAt": "2026-06-27T10:00:00Z",
                "updatedAt": "2026-06-27T10:01:00Z",
            }],
        },
        path=path,
    )

    assert payload["prompts"][0]["content"] == "Summarize this paper."
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["prompts"][0]["toolMode"] == "file"
    assert read_saved_prompts(path=path)["prompts"][0]["fileFormat"] == "markdown"


def test_saved_prompts_normalization_accepts_legacy_array_and_drops_duplicates():
    payload = normalize_saved_prompts([
        {"id": "prompt-1", "title": "", "content": "First line\nSecond line", "toolMode": "image"},
        {"id": "prompt-1", "title": "Duplicate", "content": "Duplicate content"},
        {"id": "empty", "content": "   "},
    ])

    assert payload == {
        "prompts": [{
            "id": "prompt-1",
            "title": "First line",
            "content": "First line\nSecond line",
            "toolMode": "image",
            "fileFormat": "markdown",
            "iconType": "icon",
            "iconValue": "bookmark",
            "createdAt": "",
            "updatedAt": "",
        }],
    }


def test_missing_saved_prompts_file_returns_empty_payload(tmp_path):
    assert read_saved_prompts(path=tmp_path / "missing.json") == {"prompts": []}


def test_saved_prompts_routes_round_trip(monkeypatch, tmp_path):
    path = tmp_path / ".paper-notes" / "saved-prompts.json"
    monkeypatch.setattr(saved_prompts_api, "DEFAULT_SAVED_PROMPTS_PATH", path)
    client = TestClient(create_app())

    write_response = client.post(
        "/api/saved-prompts",
        json={
            "prompts": [{
                "id": "prompt-route",
                "title": "Route prompt",
                "content": "Route content",
            }],
        },
    )
    read_response = client.get("/api/saved-prompts")

    assert write_response.status_code == 200
    assert read_response.status_code == 200
    assert read_response.json()["prompts"][0]["content"] == "Route content"
