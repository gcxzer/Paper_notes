from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def search_error(message: str, code: str, *, query: str = "") -> dict[str, Any]:
    return {
        "success": False,
        "query": query,
        "answer": "",
        "sources": [],
        "citations": [],
        "searched_at": searched_at(),
        "provider": "",
        "error": message,
        "code": code,
    }


def searched_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_limit(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))


def safe_optional_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            items.append(text)
    return items
