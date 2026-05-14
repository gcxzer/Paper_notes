from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app_infra.formatting import normalize_text


DEFAULT_BACKGROUND_RUN_TTL_SECONDS = 60 * 60


@dataclass(slots=True)
class BackgroundChatRunRecord:
    request_id: str
    session_id: str = ""
    status: str = "running"
    payload: dict[str, Any] | None = None
    error: str = ""
    code: str = ""
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def done(self) -> bool:
        return self.status in {"completed", "failed", "cancelled"}


class BackgroundChatRunStore:
    def __init__(self, *, ttl_seconds: int = DEFAULT_BACKGROUND_RUN_TTL_SECONDS) -> None:
        self.ttl_seconds = max(60, ttl_seconds)
        self._records: dict[str, BackgroundChatRunRecord] = {}
        self._lock = threading.RLock()

    def start(
        self,
        *,
        request_id: str,
        session_id: str = "",
        target: Callable[[], dict[str, Any]],
    ) -> BackgroundChatRunRecord:
        request_id = normalize_text(request_id)
        if not request_id:
            raise ValueError("request_id is required.")
        with self._lock:
            self._cleanup_locked()
            existing = self._records.get(request_id)
            if existing is not None and not existing.done:
                return existing
            record = BackgroundChatRunRecord(
                request_id=request_id,
                session_id=normalize_text(session_id),
            )
            self._records[request_id] = record

        thread = threading.Thread(
            target=self._run_target,
            args=(request_id, target),
            name=f"paper-notes-chat-run-{request_id[:24]}",
            daemon=True,
        )
        thread.start()
        return record

    def get(self, request_id: str) -> BackgroundChatRunRecord | None:
        request_id = normalize_text(request_id)
        if not request_id:
            return None
        with self._lock:
            self._cleanup_locked()
            return self._records.get(request_id)

    def _run_target(self, request_id: str, target: Callable[[], dict[str, Any]]) -> None:
        try:
            payload = target()
        except Exception as error:
            self.fail(request_id, str(error) or "Agent run failed.", code=getattr(error, "code", ""))
            return
        status = "cancelled" if payload.get("cancelled") else "completed" if payload.get("completed") else "failed"
        if status == "failed":
            self.fail(request_id, str(payload.get("error") or "Agent run failed."))
            return
        self.complete(request_id, payload, status=status)

    def complete(self, request_id: str, payload: dict[str, Any], *, status: str = "completed") -> None:
        request_id = normalize_text(request_id)
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                record = BackgroundChatRunRecord(request_id=request_id)
                self._records[request_id] = record
            record.status = status
            record.payload = payload
            record.error = ""
            record.code = ""
            record.session_id = normalize_text(payload.get("sessionId") or payload.get("session_id") or record.session_id)
            record.updated_at = time.time()

    def fail(self, request_id: str, error: str, *, code: str = "") -> None:
        request_id = normalize_text(request_id)
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                record = BackgroundChatRunRecord(request_id=request_id)
                self._records[request_id] = record
            record.status = "failed"
            record.error = normalize_text(error) or "Agent run failed."
            record.code = normalize_text(code)
            record.updated_at = time.time()

    def _cleanup_locked(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        stale = [
            request_id
            for request_id, record in self._records.items()
            if record.done and record.updated_at < cutoff
        ]
        for request_id in stale:
            self._records.pop(request_id, None)
