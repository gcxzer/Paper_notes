from __future__ import annotations

from fastapi.testclient import TestClient

from ui.backend import scratchpads_api
from ui.backend.scratchpads_api import normalize_scratchpads, read_scratchpads, write_scratchpads
from ui.backend.server import create_app


def test_scratchpads_round_trip(tmp_path):
    path = tmp_path / ".paper-notes" / "scratchpads.json"

    payload = write_scratchpads(
        {
            "activeId": "pad-2",
            "pads": [
                {"id": "pad-1", "title": "Pad 1", "content": "first"},
                {"id": "pad-2", "title": "Ideas", "customTitle": True, "content": "second"},
            ],
        },
        path=path,
    )

    assert payload["activeId"] == "pad-2"
    assert path.exists()
    assert read_scratchpads(path=path)["pads"][1]["content"] == "second"


def test_scratchpads_normalization_drops_duplicate_ids():
    payload = normalize_scratchpads(
        {
            "activeId": "pad-1",
            "pads": [
                {"id": "pad-1", "title": "", "content": "first"},
                {"id": "pad-1", "title": "Duplicate", "content": "second"},
            ],
        }
    )

    assert payload == {
        "activeId": "pad-1",
        "pads": [{
            "id": "pad-1",
            "title": "Pad 1",
            "customTitle": False,
            "content": "first",
            "updatedAt": "",
            "createdAt": "",
        }],
    }


def test_missing_scratchpads_file_returns_empty_payload(tmp_path):
    assert read_scratchpads(path=tmp_path / "missing.json") == {"activeId": "", "pads": []}


def test_scratchpads_routes_round_trip(monkeypatch, tmp_path):
    path = tmp_path / ".paper-notes" / "scratchpads.json"
    monkeypatch.setattr(scratchpads_api, "DEFAULT_SCRATCHPADS_PATH", path)
    client = TestClient(create_app())

    write_response = client.post(
        "/api/scratchpads",
        json={
            "activeId": "pad-1",
            "pads": [{"id": "pad-1", "title": "Scratch", "content": "route content"}],
        },
    )
    read_response = client.get("/api/scratchpads")

    assert write_response.status_code == 200
    assert read_response.status_code == 200
    assert read_response.json()["pads"][0]["content"] == "route content"
