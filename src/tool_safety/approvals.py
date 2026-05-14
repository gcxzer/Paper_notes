"""Approval lifecycle for local mutating tools.

Adapted from the Hermes Agent approval/permission flow, but scoped to Paper
Notes tools instead of terminal commands or gateway permissions.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent_runtime.run_control import AgentRunControl
from agent_runtime.types import AgentEvent
from app_infra.storage import atomic_write_json


APPROVAL_ACTIONS = {"allow_once", "allow_always", "deny"}
TERMINAL_APPROVAL_STATES = {"allowed", "denied", "expired", "cancelled"}
DEFAULT_APPROVAL_TIMEOUT_SECONDS = 300


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ToolApprovalError(Exception):
    """Raised when an approval request cannot be resolved."""


class ToolApprovalNotFoundError(ToolApprovalError):
    """Raised when a requested approval id does not exist or is no longer open."""


@dataclass(slots=True)
class ToolApprovalRecord:
    approval_id: str
    session_id: str
    request_id: str
    tool_call_id: str
    tool_name: str
    risk: str
    write_mode: str
    arguments: dict[str, Any] = field(default_factory=dict)
    argument_summary: str = ""
    status: str = "pending"
    decision: str = ""
    message: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    expires_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "approvalId": self.approval_id,
            "sessionId": self.session_id,
            "requestId": self.request_id,
            "toolCallId": self.tool_call_id,
            "toolName": self.tool_name,
            "risk": self.risk,
            "writeMode": self.write_mode,
            "arguments": dict(self.arguments),
            "argumentSummary": self.argument_summary,
            "status": self.status,
            "decision": self.decision,
            "message": self.message,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "expiresAt": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class ToolApprovalDecision:
    allowed: bool
    action: str
    record: ToolApprovalRecord
    reason: str = ""


class ToolApprovalManager:
    """In-memory pending approval queue with small persisted history.

    Hermes keeps pending approvals inside its event bridge and records durable
    allowlists. This local version keeps pending requests in-process so a
    synchronous HTTP run can wait while the frontend responds through another
    request.
    """

    def __init__(self, approval_root: str | Path, *, timeout_seconds: int = DEFAULT_APPROVAL_TIMEOUT_SECONDS) -> None:
        self.approval_root = Path(approval_root)
        self.state_path = self.approval_root / "approvals.json"
        self.timeout_seconds = max(5, int(timeout_seconds))
        self._condition = threading.Condition(threading.RLock())
        self._pending: dict[str, ToolApprovalRecord] = {}
        self._history: list[dict[str, Any]] = []
        self._always_allowed: set[str] = set()
        self._loaded = False

    def request_tool_approval(
        self,
        *,
        session_id: str,
        request_id: str,
        tool_call_id: str,
        tool_name: str,
        risk: str,
        write_mode: str,
        arguments: dict[str, Any],
        timeout_seconds: int | None = None,
        control: AgentRunControl | None = None,
        event_callback: Callable[[AgentEvent], None] | None = None,
    ) -> ToolApprovalDecision:
        session_id = _clean_text(session_id)
        tool_name = _clean_text(tool_name)
        tool_call_id = _clean_text(tool_call_id)
        if self.is_always_allowed(tool_name):
            record = ToolApprovalRecord(
                approval_id=f"reused-{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                request_id=_clean_text(request_id),
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                risk=_clean_text(risk) or "write",
                write_mode=_clean_text(write_mode) or "ask",
                arguments=_safe_arguments(arguments),
                argument_summary=_argument_summary(arguments),
                status="allowed",
                decision="allow_always",
                message="Previously allowed always.",
            )
            _emit(event_callback, _approval_event("tool_approval_reused", record))
            return ToolApprovalDecision(allowed=True, action="allow_always", record=record)

        timeout = max(1, int(timeout_seconds or self.timeout_seconds))
        record = ToolApprovalRecord(
            approval_id=f"approval-{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            request_id=_clean_text(request_id),
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            risk=_clean_text(risk) or "write",
            write_mode=_clean_text(write_mode) or "ask",
            arguments=_safe_arguments(arguments),
            argument_summary=_argument_summary(arguments),
            expires_at=_future_iso(timeout),
        )
        with self._condition:
            self._ensure_loaded_locked()
            self._pending[record.approval_id] = record
            self._append_history_locked(record)
            self._save_locked()
            self._condition.notify_all()

        _emit(event_callback, _approval_event("tool_approval_requested", record))
        resolved = self._wait_for_resolution(record.approval_id, timeout=timeout, control=control)
        _emit(event_callback, _approval_event("tool_approval_resolved", resolved))
        return ToolApprovalDecision(
            allowed=resolved.status == "allowed",
            action=resolved.decision or ("allow_once" if resolved.status == "allowed" else "deny"),
            record=resolved,
            reason=resolved.message,
        )

    def respond(self, approval_id: str, action: str, *, message: str = "") -> ToolApprovalRecord:
        approval_id = _clean_text(approval_id)
        action = _normalize_action(action)
        with self._condition:
            self._ensure_loaded_locked()
            record = self._pending.get(approval_id)
            if record is None:
                raise ToolApprovalNotFoundError(f"Approval is not pending: {approval_id}")
            record.status = "allowed" if action in {"allow_once", "allow_always"} else "denied"
            record.decision = action
            record.message = _clean_text(message)
            record.updated_at = _now_iso()
            if action == "allow_always":
                self._always_allowed.add(record.tool_name)
            self._append_history_locked(record)
            self._save_locked()
            self._condition.notify_all()
            return _clone_record(record)

    def list_pending(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        now = time.time()
        session_id = _clean_text(session_id)
        with self._condition:
            self._ensure_loaded_locked()
            expired = [
                approval_id
                for approval_id, record in self._pending.items()
                if record.status == "pending" and _expires_before(record, now)
            ]
            for approval_id in expired:
                self._resolve_without_decision_locked(approval_id, status="expired", message="Approval expired.")
            records = [
                record
                for record in self._pending.values()
                if record.status == "pending" and (not session_id or record.session_id == session_id)
            ]
            return [record.to_public_dict() for record in sorted(records, key=lambda item: item.created_at)]

    def is_always_allowed(self, tool_name: str) -> bool:
        tool_name = _clean_text(tool_name)
        if not tool_name:
            return False
        with self._condition:
            self._ensure_loaded_locked()
            return tool_name in self._always_allowed

    def clear(self) -> None:
        with self._condition:
            self._pending.clear()
            self._history.clear()
            self._always_allowed.clear()
            self._save_locked()
            self._condition.notify_all()

    def _wait_for_resolution(
        self,
        approval_id: str,
        *,
        timeout: int,
        control: AgentRunControl | None,
    ) -> ToolApprovalRecord:
        deadline = time.time() + timeout
        with self._condition:
            while True:
                record = self._pending.get(approval_id)
                if record is None:
                    raise ToolApprovalNotFoundError(f"Approval is not pending: {approval_id}")
                if record.status in TERMINAL_APPROVAL_STATES:
                    if record.status != "pending":
                        self._pending.pop(approval_id, None)
                    self._append_history_locked(record)
                    self._save_locked()
                    return _clone_record(record)
                if control is not None and control.cancelled:
                    return self._resolve_without_decision_locked(
                        approval_id,
                        status="cancelled",
                        message=control.reason,
                    )
                remaining = deadline - time.time()
                if remaining <= 0:
                    return self._resolve_without_decision_locked(
                        approval_id,
                        status="expired",
                        message="Approval timed out.",
                    )
                self._condition.wait(min(0.25, remaining))

    def _resolve_without_decision_locked(self, approval_id: str, *, status: str, message: str) -> ToolApprovalRecord:
        record = self._pending.get(approval_id)
        if record is None:
            raise ToolApprovalNotFoundError(f"Approval is not pending: {approval_id}")
        record.status = status
        record.decision = "deny"
        record.message = message
        record.updated_at = _now_iso()
        self._pending.pop(approval_id, None)
        self._append_history_locked(record)
        self._save_locked()
        self._condition.notify_all()
        return _clone_record(record)

    def _ensure_loaded_locked(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.state_path.is_file():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        always_allowed = payload.get("alwaysAllowed") if isinstance(payload, dict) else []
        if isinstance(always_allowed, list):
            self._always_allowed = {_clean_text(item) for item in always_allowed if _clean_text(item)}
        history = payload.get("history") if isinstance(payload, dict) else []
        if isinstance(history, list):
            self._history = [item for item in history[-200:] if isinstance(item, dict)]

    def _append_history_locked(self, record: ToolApprovalRecord) -> None:
        payload = record.to_public_dict()
        self._history = [item for item in self._history if item.get("approvalId") != record.approval_id]
        self._history.append(payload)
        self._history = self._history[-200:]

    def _save_locked(self) -> None:
        payload = {
            "version": 1,
            "alwaysAllowed": sorted(self._always_allowed),
            "history": self._history[-200:],
        }
        atomic_write_json(self.state_path, payload)


def approval_required_result(record: ToolApprovalRecord) -> dict[str, Any]:
    return {
        "success": False,
        "error": "Tool approval is required before this write can run.",
        "code": "tool_approval_required",
        "approvalId": record.approval_id,
        "toolName": record.tool_name,
    }


def approval_denied_result(record: ToolApprovalRecord) -> dict[str, Any]:
    return {
        "success": False,
        "error": record.message or "Tool approval was denied.",
        "code": "tool_approval_denied",
        "approvalId": record.approval_id,
        "toolName": record.tool_name,
        "status": record.status,
    }


def _approval_event(event_type: str, record: ToolApprovalRecord) -> AgentEvent:
    if event_type == "tool_approval_requested":
        message = f"Approval requested for tool: {record.tool_name}"
    elif event_type == "tool_approval_reused":
        message = f"Tool approval reused: {record.tool_name}"
    else:
        message = f"Tool approval resolved: {record.tool_name}"
    return AgentEvent(event_type, message, record.to_public_dict())


def _emit(callback: Callable[[AgentEvent], None] | None, event: AgentEvent) -> None:
    if callback is None:
        return
    callback(event)


def _normalize_action(action: str) -> str:
    normalized = _clean_text(action).replace("-", "_").lower()
    if normalized not in APPROVAL_ACTIONS:
        raise ValueError(f"Invalid approval action: {action}")
    return normalized


def _safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in dict(arguments or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
        elif isinstance(value, list):
            safe[str(key)] = value[:20]
        else:
            safe[str(key)] = str(value)
    return safe


def _argument_summary(arguments: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted((arguments or {}).keys()):
        value = arguments.get(key)
        text = str(value)
        if len(text) > 80:
            text = f"{text[:77]}..."
        parts.append(f"{key}={text}")
        if len(parts) >= 5:
            break
    return ", ".join(parts)


def _expires_before(record: ToolApprovalRecord, timestamp: float) -> bool:
    expires_at = _parse_iso(record.expires_at)
    return expires_at is not None and expires_at <= timestamp


def _parse_iso(value: str) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _clone_record(record: ToolApprovalRecord) -> ToolApprovalRecord:
    return ToolApprovalRecord(**asdict(record))


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _future_iso(seconds: int) -> str:
    return datetime.fromtimestamp(time.time() + max(1, seconds), timezone.utc).isoformat().replace("+00:00", "Z")
