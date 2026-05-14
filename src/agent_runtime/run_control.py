from __future__ import annotations

import threading


class AgentRunControl:
    """Thread-safe soft-cancel signal for an agent run."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._reason = ""

    def cancel(self, reason: str | None = None) -> None:
        with self._lock:
            if not self._reason:
                self._reason = (reason or "cancelled").strip() or "cancelled"
            self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason or "cancelled"

    def wait(self, timeout: float | None = None) -> bool:
        return self._cancelled.wait(timeout)
