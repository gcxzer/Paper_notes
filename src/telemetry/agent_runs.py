from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Condition, RLock

from agent_runtime import AgentRunControl


@dataclass(slots=True, eq=False)
class AgentRunHandle:
    session_id: str
    request_id: str = ""
    control: AgentRunControl = field(default_factory=AgentRunControl)
    status: str = "queued"
    queued_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class AgentRunCancelResult:
    cancelled: bool
    status: str
    request_id: str = ""
    session_id: str = ""


@dataclass(slots=True)
class _SessionRunState:
    active: AgentRunHandle | None = None
    queue: deque[AgentRunHandle] = field(default_factory=deque)


class AgentRunCoordinator:
    """Per-session FIFO guard for synchronous agent runs.

    Hermes keeps an active-session guard in the gateway adapter. This local
    version keeps the same invariant for ThreadingHTTPServer: one run per chat
    session at a time, with later requests waiting in order.
    """

    def __init__(self) -> None:
        self._condition = Condition(RLock())
        self._sessions: dict[str, _SessionRunState] = {}
        self._by_request_id: dict[str, AgentRunHandle] = {}

    def acquire(
        self,
        session_id: str,
        *,
        request_id: str = "",
        on_queued: Callable[[AgentRunHandle], None] | None = None,
        on_running: Callable[[AgentRunHandle], None] | None = None,
    ) -> AgentRunHandle | None:
        session_id = _clean_text(session_id)
        if not session_id:
            return None

        handle = AgentRunHandle(session_id=session_id, request_id=_clean_text(request_id))
        queued = False
        with self._condition:
            state = self._sessions.setdefault(session_id, _SessionRunState())
            self._index_locked(handle)
            if state.active is None and not state.queue:
                state.active = handle
                handle.status = "running"
            else:
                state.queue.append(handle)
                handle.status = "queued"
                queued = True

        if queued and on_queued is not None:
            on_queued(handle)
        if not queued and on_running is not None:
            on_running(handle)
            return handle

        with self._condition:
            while True:
                if handle.control.cancelled:
                    self._remove_handle_locked(handle)
                    self._cleanup_session_locked(session_id)
                    self._condition.notify_all()
                    return None

                state = self._sessions.get(session_id)
                if state is not None and state.active is handle:
                    handle.status = "running"
                    break
                self._condition.wait()

        if on_running is not None:
            on_running(handle)
        return handle

    def release(self, handle: AgentRunHandle | None) -> None:
        if handle is None:
            return
        with self._condition:
            state = self._sessions.get(handle.session_id)
            if state is None:
                return

            if state.active is handle:
                state.active = None
                self._unindex_locked(handle)
                self._promote_next_locked(state)
            else:
                self._remove_handle_locked(handle)

            self._cleanup_session_locked(handle.session_id)
            self._condition.notify_all()

    def cancel(
        self,
        *,
        request_id: str = "",
        session_id: str = "",
        reason: str = "cancelled",
    ) -> AgentRunCancelResult:
        with self._condition:
            handle = self._find_handle_locked(request_id=request_id, session_id=session_id)
            if handle is None:
                return AgentRunCancelResult(
                    cancelled=False,
                    status="not_found",
                    request_id=_clean_text(request_id),
                    session_id=_clean_text(session_id),
                )

            handle.control.cancel(reason)
            result = AgentRunCancelResult(
                cancelled=True,
                status="cancelled",
                request_id=handle.request_id,
                session_id=handle.session_id,
            )
            if handle.status == "queued":
                self._remove_handle_locked(handle)
                self._cleanup_session_locked(handle.session_id)
            else:
                handle.status = "cancelling"
            self._condition.notify_all()
            return result

    def clear(self) -> None:
        with self._condition:
            self._sessions.clear()
            self._by_request_id.clear()
            self._condition.notify_all()

    def _promote_next_locked(self, state: _SessionRunState) -> None:
        while state.queue:
            next_handle = state.queue.popleft()
            if next_handle.control.cancelled:
                self._unindex_locked(next_handle)
                continue
            next_handle.status = "running"
            state.active = next_handle
            return

    def _find_handle_locked(self, *, request_id: str, session_id: str) -> AgentRunHandle | None:
        request_id = _clean_text(request_id)
        if request_id:
            return self._by_request_id.get(request_id)

        session_id = _clean_text(session_id)
        if not session_id:
            return None
        state = self._sessions.get(session_id)
        if state is None:
            return None
        if state.active is not None:
            return state.active
        return state.queue[0] if state.queue else None

    def _remove_handle_locked(self, handle: AgentRunHandle) -> None:
        state = self._sessions.get(handle.session_id)
        if state is None:
            self._unindex_locked(handle)
            return
        if state.active is handle:
            state.active = None
            self._promote_next_locked(state)
        else:
            try:
                state.queue.remove(handle)
            except ValueError:
                pass
        self._unindex_locked(handle)

    def _cleanup_session_locked(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if state is not None and state.active is None and not state.queue:
            del self._sessions[session_id]

    def _index_locked(self, handle: AgentRunHandle) -> None:
        if handle.request_id:
            self._by_request_id[handle.request_id] = handle

    def _unindex_locked(self, handle: AgentRunHandle) -> None:
        if handle.request_id and self._by_request_id.get(handle.request_id) is handle:
            del self._by_request_id[handle.request_id]


def _clean_text(value: object) -> str:
    return str(value or "").strip()
