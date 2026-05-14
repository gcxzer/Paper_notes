from __future__ import annotations

import json

from app_infra.storage import atomic_write_json, atomic_write_text


def test_atomic_write_json_round_trips(tmp_path):
    target = tmp_path / "nested" / "data.json"

    atomic_write_json(target, {"hello": "世界"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"hello": "世界"}


def test_atomic_write_text_replaces_existing_file(tmp_path):
    target = tmp_path / "value.txt"
    target.write_text("old", encoding="utf-8")

    atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
