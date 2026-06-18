from __future__ import annotations

from fastapi.testclient import TestClient

import library.store as library_module
from library import read_library, write_library
from ui.backend.server import create_app


def test_library_delete_endpoint_removes_note_from_persisted_library(tmp_path, monkeypatch):
    notes_path = tmp_path / "notes.json"
    monkeypatch.setattr(library_module, "NOTES_PATH", notes_path)
    write_library(
        {
            "notes": [
                {"id": "note-1", "title": "First Paper", "categoryId": "uncategorized"},
                {"id": "note-2", "title": "Second Paper", "categoryId": "uncategorized"},
            ],
        },
        notes_path,
    )

    response = TestClient(create_app()).delete("/api/library/notes/note-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["note"]["id"] == "note-1"
    assert [note["id"] for note in payload["library"]["notes"]] == ["note-2"]
    assert [note["id"] for note in read_library(notes_path)["notes"]] == ["note-2"]


def test_library_write_endpoint_persists_collections(tmp_path, monkeypatch):
    notes_path = tmp_path / "notes.json"
    monkeypatch.setattr(library_module, "NOTES_PATH", notes_path)
    client = TestClient(create_app())

    response = client.post(
        "/api/library",
        json={
            "library": {
                "categories": [
                    {"id": "paper-rag", "name": "Paper RAG", "parentId": None, "order": 2},
                ],
                "notes": [
                    {"id": "note-1", "title": "Indexed Paper", "categoryId": "paper-rag"},
                ],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert {category["id"] for category in response.json()["library"]["categories"]} >= {"paper-rag"}
    persisted = read_library(notes_path)
    assert {category["id"] for category in persisted["categories"]} >= {"paper-rag"}
    assert persisted["notes"][0]["categoryId"] == "paper-rag"
    assert client.get("/api/library").json()["library"] == persisted


def test_library_delete_endpoint_returns_404_for_missing_note(tmp_path, monkeypatch):
    notes_path = tmp_path / "notes.json"
    monkeypatch.setattr(library_module, "NOTES_PATH", notes_path)
    write_library({"notes": []}, notes_path)

    response = TestClient(create_app()).delete("/api/library/notes/missing")

    assert response.status_code == 404
    assert response.json()["success"] is False
