from __future__ import annotations

from typing import Any

from agent_memory import MEMORY_TARGET, USER_TARGET, LocalMemoryStore


VALID_MEMORY_TARGETS = {MEMORY_TARGET, USER_TARGET}


def list_memory(*, store: LocalMemoryStore | None = None) -> dict[str, Any]:
    memory_store = store or LocalMemoryStore()
    return _memory_payload(memory_store)


def update_memory(body: Any, *, store: LocalMemoryStore | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Memory request body must be an object.")

    memory_store = store or LocalMemoryStore()
    action = _text(body.get("action") or "read").lower()
    target = _target(body.get("target"))

    if action == "read":
        memory_store.read(target)
        return _memory_payload(memory_store)

    if action == "add":
        result = memory_store.add(_text(body.get("content")), target=target)
    elif action == "update":
        result = memory_store.replace(
            target,
            old_text=_old_text_for_body(memory_store, body, target),
            content=_text(body.get("content")),
        )
    elif action == "delete":
        result = memory_store.remove(
            target,
            old_text=_old_text_for_body(memory_store, body, target),
        )
    else:
        raise ValueError("Unknown memory action. Use add, update, delete, or read.")

    if not result.get("success"):
        raise ValueError(str(result.get("error") or "Memory update failed."))

    return {
        **_memory_payload(memory_store),
        "result": result,
    }


def _memory_payload(memory_store: LocalMemoryStore) -> dict[str, Any]:
    memory_store.load_from_disk()
    entries = [
        *_entries_for_target(memory_store, USER_TARGET),
        *_entries_for_target(memory_store, MEMORY_TARGET),
    ]
    return {
        "targets": [
            {"id": USER_TARGET, "label": "User profile"},
            {"id": MEMORY_TARGET, "label": "Project memory"},
        ],
        "entries": entries,
        "counts": {
            USER_TARGET: sum(1 for entry in entries if entry["target"] == USER_TARGET),
            MEMORY_TARGET: sum(1 for entry in entries if entry["target"] == MEMORY_TARGET),
        },
    }


def _entries_for_target(memory_store: LocalMemoryStore, target: str) -> list[dict[str, Any]]:
    entries = memory_store.read(target).get("entries", [])
    return [
        {
            "id": f"{target}:{index}",
            "target": target,
            "index": index,
            "content": content,
            "charCount": len(content),
        }
        for index, content in enumerate(entries)
    ]


def _old_text_for_body(memory_store: LocalMemoryStore, body: dict[str, Any], target: str) -> str:
    old_text = _text(body.get("oldText") or body.get("old_text"))
    if old_text:
        return old_text

    index = _optional_index(body.get("index"))
    if index is None:
        entry_id = _text(body.get("id"))
        if entry_id.startswith(f"{target}:"):
            index = _optional_index(entry_id.split(":", 1)[1])
    if index is None:
        raise ValueError("Memory index or oldText is required.")

    entries = memory_store.read(target).get("entries", [])
    if index < 0 or index >= len(entries):
        raise ValueError("Memory entry was not found.")
    return str(entries[index])


def _target(value: Any) -> str:
    target = _text(value or USER_TARGET).lower()
    if target not in VALID_MEMORY_TARGETS:
        raise ValueError("Memory target must be 'user' or 'memory'.")
    return target


def _optional_index(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()
