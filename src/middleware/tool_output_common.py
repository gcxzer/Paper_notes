from __future__ import annotations

import json
import re
from typing import Any


PLACEHOLDER_PREFIX = "[tool output omitted]"
SAVED_PATH_RE = re.compile(r"^Full output path:\s*(?P<path>.+)$", re.MULTILINE)


def tool_output_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True)
    except TypeError:
        return str(content)


def saved_output_path(content: str) -> str:
    match = SAVED_PATH_RE.search(content)
    return match.group("path").strip() if match else ""


def is_placeholder_content(content: Any) -> bool:
    return tool_output_text(content).startswith(PLACEHOLDER_PREFIX)


def truncate_output_text(text: str, *, max_tokens: int, chars_per_token: int = 4) -> str:
    max_chars = max(1, int(max_tokens) * max(1, int(chars_per_token)))
    return str(text or "")[:max_chars].rstrip()


def safe_output_segment(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    text = re.sub(r"-{2,}", "-", text).strip(".-")
    return text[:80] or "tool"


__all__ = [
    "PLACEHOLDER_PREFIX",
    "is_placeholder_content",
    "safe_output_segment",
    "saved_output_path",
    "tool_output_text",
    "truncate_output_text",
]
