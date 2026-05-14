from __future__ import annotations

import pytest

from agent_memory import MEMORY_TARGET, USER_TARGET, LocalMemoryStore
from backend.memory_api import list_memory, update_memory


def test_list_memory_returns_both_targets(tmp_path):
    store = LocalMemoryStore(tmp_path / "memory")
    store.add("User prefers concise answers.", target=USER_TARGET)
    store.add("Project uses pytest.", target=MEMORY_TARGET)

    payload = list_memory(store=store)

    assert payload["counts"] == {"user": 1, "memory": 1}
    assert [entry["id"] for entry in payload["entries"]] == ["user:0", "memory:0"]
    assert payload["entries"][0]["content"] == "User prefers concise answers."


def test_update_memory_add_update_delete(tmp_path):
    store = LocalMemoryStore(tmp_path / "memory")

    added = update_memory({"action": "add", "target": "user", "content": "User prefers Chinese."}, store=store)
    updated = update_memory({
        "action": "update",
        "target": "user",
        "index": 0,
        "content": "User prefers concise Chinese.",
    }, store=store)
    deleted = update_memory({"action": "delete", "target": "user", "id": "user:0"}, store=store)

    assert added["entries"][0]["content"] == "User prefers Chinese."
    assert updated["entries"][0]["content"] == "User prefers concise Chinese."
    assert deleted["counts"]["user"] == 0


def test_update_memory_rejects_invalid_target(tmp_path):
    store = LocalMemoryStore(tmp_path / "memory")

    with pytest.raises(ValueError, match="target"):
        update_memory({"action": "add", "target": "other", "content": "x"}, store=store)
