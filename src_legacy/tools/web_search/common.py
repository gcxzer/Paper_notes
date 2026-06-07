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
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "provider": "",
        "error": message,
        "code": code,
    }


def searched_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def search_prompt(
    query: str,
    *,
    limit: int,
    allowed_domains: list[str],
    recency_days: int | None,
    include_summary: bool,
) -> str:
    constraints: list[str] = [f"Return at most {limit} useful sources."]
    if allowed_domains:
        constraints.append("Prefer these domains: " + ", ".join(allowed_domains) + ".")
    if recency_days:
        constraints.append(f"Prefer results from the last {recency_days} days.")
    if include_summary:
        constraints.append("Include a concise answer before the sources.")
    else:
        constraints.append("Do not synthesize a long answer; focus on sources.")
    return f"Search the web for: {query}\n\n" + "\n".join(f"- {item}" for item in constraints)


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
