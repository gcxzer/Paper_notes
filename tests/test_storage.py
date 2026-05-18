from __future__ import annotations

import errno
import json
import os

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


def test_atomic_write_text_falls_back_for_busy_bind_mount_file(tmp_path, monkeypatch):
    target = tmp_path / "notes.json"
    target.write_text("old", encoding="utf-8")
    original_replace = os.replace

    def busy_replace(source, destination):
        if destination == str(target):
            raise OSError(errno.EBUSY, "Device or resource busy")
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", busy_replace)

    atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".notes_*.tmp"))
