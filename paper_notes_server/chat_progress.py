from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Any

from .storage import normalize_text


REQUEST_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{7,160}$")
MAX_EVENTS = 12

_progress_store: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_request_id(value: object) -> str:
    request_id = normalize_text(value)
    return request_id if REQUEST_ID_PATTERN.match(request_id) else ""


def set_chat_progress(request_id: object, stage: str, detail: str) -> None:
    safe_request_id = normalize_request_id(request_id)
    if not safe_request_id:
        return

    timestamp = now_iso()
    event = {
        "stage": normalize_text(stage) or "working",
        "detail": normalize_text(detail) or "Working...",
        "at": timestamp,
    }

    with _lock:
        current = _progress_store.get(safe_request_id) or {
            "requestId": safe_request_id,
            "stage": "queued",
            "detail": "Queued.",
            "status": "running",
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "events": [],
        }
        events = current.get("events") if isinstance(current.get("events"), list) else []
        if not events or events[-1].get("stage") != event["stage"] or events[-1].get("detail") != event["detail"]:
            events = [*events, event][-MAX_EVENTS:]
        current.update(
            {
                "stage": event["stage"],
                "detail": event["detail"],
                "status": "running",
                "updatedAt": timestamp,
                "events": events,
            }
        )
        _progress_store[safe_request_id] = current


def complete_chat_progress(request_id: object, detail: str = "Answer ready.") -> None:
    finish_chat_progress(request_id, "done", "complete", detail)


def fail_chat_progress(request_id: object, detail: str = "Agent request failed.") -> None:
    finish_chat_progress(request_id, "error", "failed", detail)


def finish_chat_progress(request_id: object, stage: str, status: str, detail: str) -> None:
    safe_request_id = normalize_request_id(request_id)
    if not safe_request_id:
        return
    set_chat_progress(safe_request_id, stage, detail)
    with _lock:
        current = _progress_store.get(safe_request_id)
        if current:
            current["status"] = status
            current["updatedAt"] = now_iso()


def get_chat_progress(request_id: object) -> dict[str, Any] | None:
    safe_request_id = normalize_request_id(request_id)
    if not safe_request_id:
        return None
    with _lock:
        current = _progress_store.get(safe_request_id)
        return dict(current) if current else None
