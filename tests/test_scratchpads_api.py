from __future__ import annotations

from ui.backend.scratchpads_api import normalize_scratchpads, read_scratchpads, write_scratchpads


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
