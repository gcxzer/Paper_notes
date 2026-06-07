from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app_config.secrets import LOCAL_STATE_DIR
from app_infra.storage import atomic_write_json


_REDACTED = "[redacted]"
_LARGE_STRING_REDACTED = "[large-string-redacted]"
_IMAGE_DATA_REDACTED = "[image-data-url-redacted]"
_MAX_DEBUG_STRING = 4000
_MAX_DEBUG_ITEMS = 200
_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|authorization|bearer|token|secret|password|credential|refresh[_-]?token|access[_-]?token)",
    re.IGNORECASE,
)
_SAFE_TOKEN_METRIC_KEYS = frozenset({
    "after_estimated_tokens",
    "before_estimated_tokens",
    "cache_deleted_input_tokens",
    "cached_input_tokens",
    "completion_tokens",
    "input_tokens",
    "message_after_estimated_tokens",
    "message_before_estimated_tokens",
    "output_tokens",
    "prompt_tokens",
    "reasoning_tokens",
    "total_tokens",
})
_IMAGE_DATA_URL_PATTERN = re.compile(r"^data:image/[a-z0-9.+-]+;base64,", re.IGNORECASE)
_BASE64ISH_PATTERN = re.compile(r"^[A-Za-z0-9+/=\s]+$")


@dataclass(slots=True)
class DebugRunRecord:
    requestId: str
    sessionId: str = ""
    noteId: str = ""
    provider: str = ""
    model: str = ""
    transport: str = "json"
    status: str = "running"
    startedAt: str = ""
    finishedAt: str = ""
    durationMs: int = 0
    error: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    transcriptPath: str = ""
    finalMessagePreview: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requestId": self.requestId,
            "sessionId": self.sessionId,
            "noteId": self.noteId,
            "provider": self.provider,
            "model": self.model,
            "transport": self.transport,
            "status": self.status,
            "startedAt": self.startedAt,
            "finishedAt": self.finishedAt,
            "durationMs": self.durationMs,
            "error": self.error,
            "events": self.events,
            "transcriptPath": self.transcriptPath,
            "finalMessagePreview": self.finalMessagePreview,
            "metadata": self.metadata,
        }


class DebugRunStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else LOCAL_STATE_DIR / "logs" / "runs"

    def start_run(
        self,
        *,
        request_id: str,
        session_id: str = "",
        note_id: str = "",
        provider: str = "",
        model: str = "",
        transport: str = "json",
        metadata: dict[str, Any] | None = None,
    ) -> DebugRunRecord:
        started_at = _now_iso()
        record = DebugRunRecord(
            requestId=request_id,
            sessionId=session_id,
            noteId=note_id,
            provider=provider,
            model=model,
            transport=transport,
            startedAt=started_at,
            metadata=sanitize_debug_payload(metadata or {}),
        )
        self.write(record)
        return record

    def finish_run(
        self,
        request_id: str,
        *,
        status: str,
        session_id: str = "",
        note_id: str = "",
        provider: str = "",
        model: str = "",
        error: dict[str, Any] | str | None = None,
        events: list[dict[str, Any]] | None = None,
        transcript_path: str = "",
        final_message_preview: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DebugRunRecord:
        current = self.get_run(request_id) or {
            "requestId": request_id,
            "transport": "json",
            "status": "running",
            "startedAt": _now_iso(),
        }
        started_at = str(current.get("startedAt") or _now_iso())
        finished_at = _now_iso()
        record = DebugRunRecord(
            requestId=request_id,
            sessionId=session_id or str(current.get("sessionId") or ""),
            noteId=note_id or str(current.get("noteId") or ""),
            provider=provider or str(current.get("provider") or ""),
            model=model or str(current.get("model") or ""),
            transport=str(current.get("transport") or "json"),
            status=status,
            startedAt=started_at,
            finishedAt=finished_at,
            durationMs=_duration_ms(started_at, finished_at),
            error=_normalize_error(error),
            events=sanitize_debug_payload(events or current.get("events") or []),
            transcriptPath=transcript_path or str(current.get("transcriptPath") or ""),
            finalMessagePreview=_preview_text(final_message_preview),
            metadata=sanitize_debug_payload({
                **(current.get("metadata") if isinstance(current.get("metadata"), dict) else {}),
                **(metadata or {}),
            }),
        )
        self.write(record)
        return record

    def write(self, record: DebugRunRecord | dict[str, Any]) -> None:
        data = record.to_dict() if isinstance(record, DebugRunRecord) else dict(record)
        request_id = _safe_request_id(str(data.get("requestId") or ""))
        if not request_id:
            return
        started_at = str(data.get("startedAt") or _now_iso())
        path = self._record_path(request_id, started_at=started_at)
        atomic_write_json(path, sanitize_debug_payload(data), indent=2)

    def list_runs(self, *, limit: int = 50, session_id: str = "", status: str = "") -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 50), 500))
        session_id = str(session_id or "")
        status = str(status or "")
        records = []
        for path in self._record_files():
            data = _read_json(path)
            if not isinstance(data, dict):
                continue
            if session_id and data.get("sessionId") != session_id:
                continue
            if status and data.get("status") != status:
                continue
            records.append(_list_item(data))
        records.sort(key=lambda item: str(item.get("startedAt") or item.get("finishedAt") or ""), reverse=True)
        return records[:limit]

    def get_run(self, request_id: str) -> dict[str, Any] | None:
        safe_id = _safe_request_id(request_id)
        if not safe_id:
            return None
        matches = sorted(self.root.glob(f"*/{safe_id}.json"), reverse=True)
        for path in matches:
            data = _read_json(path)
            if isinstance(data, dict):
                return sanitize_debug_payload(data)
        return None

    def cleanup(self, *, keep: int = 200, max_age_days: int = 30) -> dict[str, Any]:
        keep = max(0, int(keep or 0))
        max_age_days = max(1, int(max_age_days or 30))
        now = datetime.now().astimezone()
        files = []
        for path in self._record_files():
            data = _read_json(path)
            if not isinstance(data, dict):
                continue
            timestamp = _parse_datetime(str(data.get("startedAt") or data.get("finishedAt") or ""))
            files.append((timestamp or datetime.fromtimestamp(path.stat().st_mtime).astimezone(), path))
        files.sort(key=lambda item: item[0], reverse=True)
        keep_paths = {path for _, path in files[:keep]}
        deleted = 0
        cutoff = now - timedelta(days=max_age_days)
        for timestamp, path in files:
            if path in keep_paths and timestamp >= cutoff:
                continue
            try:
                path.unlink()
                deleted += 1
            except OSError:
                continue
        return {"deletedCount": deleted, "kept": max(0, len(files) - deleted)}

    def _record_path(self, request_id: str, *, started_at: str) -> Path:
        timestamp = _parse_datetime(started_at) or datetime.now().astimezone()
        bucket = timestamp.strftime("%Y_%m_%d")
        return self.root / bucket / f"{_safe_request_id(request_id)}.json"

    def _record_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        return [path for path in self.root.glob("*/*.json") if path.is_file()]


def sanitize_debug_payload(value: Any, *, _depth: int = 0) -> Any:
    if _depth > 12:
        return "[max-depth-redacted]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_DEBUG_ITEMS:
                sanitized["__truncated__"] = True
                break
            text_key = str(key)
            if _is_safe_token_metric(text_key, item):
                sanitized[text_key] = item
            elif _SECRET_KEY_PATTERN.search(text_key):
                sanitized[text_key] = _REDACTED
            else:
                sanitized[text_key] = sanitize_debug_payload(item, _depth=_depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        items = [sanitize_debug_payload(item, _depth=_depth + 1) for item in list(value)[:_MAX_DEBUG_ITEMS]]
        if len(value) > _MAX_DEBUG_ITEMS:
            items.append({"__truncated__": True, "count": len(value)})
        return items
    if isinstance(value, str):
        if _IMAGE_DATA_URL_PATTERN.match(value):
            return _IMAGE_DATA_REDACTED
        if len(value) > _MAX_DEBUG_STRING and _BASE64ISH_PATTERN.match(value[:2000]):
            return f"{_LARGE_STRING_REDACTED}:{len(value)}"
        if len(value) > _MAX_DEBUG_STRING:
            return f"{value[:_MAX_DEBUG_STRING]}...[truncated:{len(value) - _MAX_DEBUG_STRING}]"
        return value
    return value


def _is_safe_token_metric(key: str, value: Any) -> bool:
    normalized = key.strip().lower()
    return normalized in _SAFE_TOKEN_METRIC_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize_error(error: dict[str, Any] | str | None) -> dict[str, Any] | None:
    if error is None:
        return None
    if isinstance(error, dict):
        return sanitize_debug_payload(error)
    return {"message": sanitize_debug_payload(str(error))}


def _list_item(data: dict[str, Any]) -> dict[str, Any]:
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    error_preview = str(error.get("message") or error.get("error") or error.get("code") or "") if error else ""
    return {
        "requestId": data.get("requestId") or "",
        "status": data.get("status") or "",
        "provider": data.get("provider") or "",
        "model": data.get("model") or "",
        "transport": data.get("transport") or "",
        "sessionId": data.get("sessionId") or "",
        "noteId": data.get("noteId") or "",
        "startedAt": data.get("startedAt") or "",
        "finishedAt": data.get("finishedAt") or "",
        "durationMs": data.get("durationMs") or 0,
        "errorPreview": _preview_text(error_preview, max_chars=240),
        "finalMessagePreview": _preview_text(str(data.get("finalMessagePreview") or ""), max_chars=240),
    }


def _preview_text(value: str, *, max_chars: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_chars]


def _duration_ms(started_at: str, finished_at: str) -> int:
    start = _parse_datetime(started_at)
    finish = _parse_datetime(finished_at)
    if not start or not finish:
        return 0
    return max(0, int((finish - start).total_seconds() * 1000))


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone() if parsed.tzinfo is not None else parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _safe_request_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip())[:160]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
