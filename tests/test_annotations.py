from __future__ import annotations

from backend.annotations import annotation_path_for, read_annotations, write_annotations


def test_annotation_path_sanitizes_note_id(tmp_path):
    path = annotation_path_for("../bad id", tmp_path)

    assert path == tmp_path / "bad-id.json"


def test_annotations_round_trip(tmp_path):
    payload = write_annotations("note-1", [{"id": "a1", "page": 1}], tmp_path)

    assert payload == {"annotations": [{"id": "a1", "page": 1}]}
    assert read_annotations("note-1", tmp_path) == payload
