from __future__ import annotations

from backend.library import read_library, sanitize_library, write_library


def test_sanitize_library_strips_legacy_cloud_fields():
    library = sanitize_library({
        "categories": [],
        "notes": [{
            "id": "note-1",
            "title": "Paper",
            "categoryId": "missing",
            "pdfS3Key": "legacy",
            "kbPaperS3Key": "legacy",
            "kbSyncStatus": "legacy",
        }],
    })

    note = library["notes"][0]
    assert note["categoryId"] == "uncategorized"
    assert "pdfS3Key" not in note
    assert "kbPaperS3Key" not in note
    assert "kbSyncStatus" not in note


def test_sanitize_library_keeps_notes_only_in_leaf_categories():
    library = sanitize_library({
        "categories": [
            {"id": "parent", "name": "Parent", "parentId": None, "order": 2},
            {"id": "child", "name": "Child", "parentId": "parent", "order": 0},
        ],
        "notes": [{"id": "note-1", "title": "Paper", "categoryId": "parent"}],
    })

    assert library["notes"][0]["categoryId"] == "uncategorized"


def test_write_library_uses_sanitized_shape(tmp_path):
    target = tmp_path / "notes.json"
    write_library({"notes": [{"id": "note-1", "title": "Paper", "pdfS3Key": "legacy"}]}, target)

    loaded = read_library(target)

    assert loaded["notes"][0]["title"] == "Paper"
    assert "pdfS3Key" not in loaded["notes"][0]
