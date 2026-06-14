from __future__ import annotations

from fastapi.testclient import TestClient

from ui.backend import server
from ui.backend.server import create_app


def test_annotations_get_reads_note_annotations(monkeypatch):
    calls: list[str] = []

    def fake_read_annotations(note_id: str):
        calls.append(note_id)
        return {"annotations": [{"id": "a1", "page": 1}]}

    monkeypatch.setattr(server, "read_annotations", fake_read_annotations)

    response = TestClient(create_app()).get("/api/annotations", params={"noteId": "note-1"})

    assert response.status_code == 200
    assert response.json() == {"annotations": [{"id": "a1", "page": 1}]}
    assert calls == ["note-1"]


def test_annotations_post_writes_note_annotations(monkeypatch):
    calls: list[tuple[str, list[dict[str, object]]]] = []

    def fake_write_annotations(note_id: str, annotations):
        calls.append((note_id, annotations))
        return {"annotations": annotations}

    monkeypatch.setattr(server, "write_annotations", fake_write_annotations)

    response = TestClient(create_app()).post(
        "/api/annotations",
        json={"noteId": "note-1", "annotations": [{"id": "a1", "page": 1}]},
    )

    assert response.status_code == 200
    assert response.json() == {"annotations": [{"id": "a1", "page": 1}]}
    assert calls == [("note-1", [{"id": "a1", "page": 1}])]


def test_annotations_requires_note_id():
    client = TestClient(create_app())

    get_response = client.get("/api/annotations")
    post_response = client.post("/api/annotations", json={"annotations": []})

    assert get_response.status_code == 400
    assert get_response.json()["code"] == "noteId_required"
    assert post_response.status_code == 400
    assert post_response.json()["code"] == "noteId_required"
