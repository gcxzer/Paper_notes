from __future__ import annotations

import re
from typing import Any

from tools.mcp.security import sanitize_mcp_error
from tools.mcp.utils import format_exception

__all__ = [
    "is_session_expired_error",
    "mcp_error_payload",
]

_RATE_LIMIT_ERROR_MARKERS = (
    "rate limit",
    "rate-limit",
    "too many requests",
    "retry-after",
    "retry after",
    "retryafter",
    "http 429",
    "status 429",
    "429 too many",
)
_TIMEOUT_ERROR_MARKERS = (
    "timed out",
    "timeout",
    "deadline exceeded",
)
_SESSION_EXPIRED_MARKERS = (
    "invalid or expired session",
    "expired session",
    "session expired",
    "session not found",
    "unknown session",
    "session terminated",
    "closedresourceerror",
    "closed resource",
    "transport is closed",
    "connection closed",
    "broken pipe",
    "end of file",
)


def mcp_error_payload(
    error_text: Any,
    *,
    server_id: str,
    default_code: str = "mcp_tool_error",
    details: Any = None,
) -> dict[str, Any]:
    safe_error = sanitize_mcp_error(error_text)
    code = mcp_error_code(safe_error, default_code=default_code)
    payload: dict[str, Any] = {
        "success": False,
        "error": safe_error,
        "code": code,
        "server_id": server_id,
    }
    if code == "mcp_rate_limited":
        retry_after = extract_retry_after_seconds(details, error_text)
        payload["retry"] = {
            "allowed": True,
            "immediate": False,
            "reason": "rate_limited",
        }
        if retry_after is not None:
            payload["retry"]["afterSeconds"] = retry_after
        payload["recovery"] = "Do not retry immediately. Wait for the remote MCP server cooldown before retrying."
    elif code == "mcp_timeout":
        payload["retry"] = {
            "allowed": True,
            "immediate": False,
            "reason": "timeout",
        }
        payload["recovery"] = "Do not retry repeatedly in the same turn. Retry later or increase the MCP tool timeout."
    return payload


def mcp_error_code(error_text: Any, *, default_code: str) -> str:
    text = str(error_text or "").lower()
    if any(marker in text for marker in _RATE_LIMIT_ERROR_MARKERS):
        return "mcp_rate_limited"
    if any(marker in text for marker in _TIMEOUT_ERROR_MARKERS):
        return "mcp_timeout"
    return default_code


def extract_retry_after_seconds(*values: Any) -> int | None:
    for value in values:
        found = find_retry_after_value(value)
        if found is None:
            continue
        try:
            seconds = int(float(str(found).strip()))
        except (TypeError, ValueError):
            continue
        if seconds >= 0:
            return seconds
    return None


def find_retry_after_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").replace("_", "").replace("-", "").lower()
            if normalized_key in {"retryafter", "retryafterseconds"}:
                return item
            found = find_retry_after_value(item)
            if found is not None:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            found = find_retry_after_value(item)
            if found is not None:
                return found
        return None
    text = str(value or "")
    match = re.search(r"(?i)\bretry[-_\s]*after(?:\s*seconds)?\s*[:=]\s*(\d+(?:\.\d+)?)", text)
    if match:
        return match.group(1)
    return None


def is_session_expired_error(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {format_exception(error)}".lower()
    return any(marker in text for marker in _SESSION_EXPIRED_MARKERS)

