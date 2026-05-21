from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from agent_runtime import AgentEvent
from agent_runtime.tool_trace import read_paper_progress_detail


DEFAULT_PROGRESS_TTL_SECONDS = 30 * 60
DEFAULT_MAX_EVENTS = 40


# ---------------------------------------------------------------------------
# Progress records and in-memory store
#
# The agent runtime emits AgentEvent objects while a run is active. This module
# keeps a short-lived, pollable progress snapshot per request_id so the UI can
# show status, visible progress rows, and work-trace items during synchronous
# HTTP requests.
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class AgentProgressRecord:
    request_id: str
    status: str = "running"
    stage: str = "starting"
    detail: str = "Starting agent run."
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    expires_at: float = field(default_factory=lambda: time.time() + DEFAULT_PROGRESS_TTL_SECONDS)
    events: list[dict[str, Any]] = field(default_factory=list)
    visible_stage: str = "starting"
    visible_detail: str = "Starting agent run."
    visible_events: list[dict[str, Any]] = field(default_factory=list)
    work_trace_items: list[dict[str, Any]] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "status": self.status,
            "stage": self.stage,
            "detail": self.detail,
            "visibleStage": self.visible_stage,
            "visibleDetail": self.visible_detail,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "events": list(self.events),
            "visibleEvents": list(self.visible_events),
            "workTrace": {
                "status": self.status,
                "items": [_public_work_trace_item(item) for item in self.work_trace_items],
            },
        }


class AgentProgressStore:
    """Small in-memory progress bridge for synchronous HTTP agent runs.

    Hermes emits status/tool callbacks from the agent core and lets the gateway
    decide how to render them. This store keeps the same boundary for the local
    app: runtime events come in, HTTP polling snapshots go out.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_PROGRESS_TTL_SECONDS,
        max_events: int = DEFAULT_MAX_EVENTS,
    ) -> None:
        self.ttl_seconds = max(60, ttl_seconds)
        self.max_events = max(1, max_events)
        self._records: dict[str, AgentProgressRecord] = {}
        self._lock = Lock()

    def start(self, request_id: str) -> dict[str, Any]:
        request_id = _clean_text(request_id)
        if not request_id:
            return {}
        with self._lock:
            self._cleanup_locked()
            record = AgentProgressRecord(
                request_id=request_id,
                expires_at=time.time() + self.ttl_seconds,
            )
            self._records[request_id] = record
            return record.snapshot()

    def queued(self, request_id: str, *, detail: str | None = None) -> dict[str, Any]:
        return self._set_status(
            request_id,
            status="queued",
            stage="queued",
            detail=detail or "Waiting for the current session run to finish.",
        )

    def running(self, request_id: str, *, detail: str | None = None) -> dict[str, Any]:
        return self._set_status(
            request_id,
            status="running",
            stage="running",
            detail=detail or "Agent run started.",
        )

    def cancelling(self, request_id: str, *, detail: str | None = None) -> dict[str, Any]:
        return self._set_status(
            request_id,
            status="cancelling",
            stage="cancelling",
            detail=detail or "Cancelling agent run.",
        )

    def cancelled(self, request_id: str, *, detail: str | None = None) -> dict[str, Any]:
        return self._finish(
            request_id,
            status="cancelled",
            stage="cancelled",
            detail=detail or "Agent run cancelled.",
        )

    def append(self, request_id: str, event: AgentEvent) -> dict[str, Any]:
        request_id = _clean_text(request_id)
        if not request_id:
            return {}
        with self._lock:
            self._cleanup_locked()
            record = self._records.get(request_id)
            if record is None:
                record = AgentProgressRecord(
                    request_id=request_id,
                    expires_at=time.time() + self.ttl_seconds,
                )
                self._records[request_id] = record

            progress_event = _progress_event(event)
            visible_event = _visible_progress_event(event, progress_event)
            work_trace_item = _work_trace_item(event, progress_event, visible_event)
            record.events.append(progress_event)
            if len(record.events) > self.max_events:
                record.events = record.events[-self.max_events :]
            if visible_event is not None:
                if not _has_visible_event(record.visible_events, visible_event):
                    record.visible_events.append(visible_event)
                if len(record.visible_events) > self.max_events:
                    record.visible_events = record.visible_events[-self.max_events :]
                record.visible_stage = visible_event["stage"]
                record.visible_detail = visible_event["detail"]
            if work_trace_item is not None:
                _merge_work_trace_item(record.work_trace_items, work_trace_item)
                if len(record.work_trace_items) > self.max_events:
                    record.work_trace_items = record.work_trace_items[-self.max_events :]
            record.status = _status_for_event(event) or record.status
            record.stage = progress_event["stage"]
            record.detail = progress_event["detail"]
            record.updated_at = progress_event["at"]
            record.expires_at = time.time() + self.ttl_seconds
            return record.snapshot()

    def complete(self, request_id: str, *, detail: str | None = None) -> dict[str, Any]:
        return self._finish(request_id, status="completed", stage="completed", detail=detail or "Agent run completed.")

    def fail(self, request_id: str, detail: str) -> dict[str, Any]:
        return self._finish(request_id, status="failed", stage="failed", detail=detail or "Agent run failed.")

    def get(self, request_id: str) -> dict[str, Any] | None:
        request_id = _clean_text(request_id)
        if not request_id:
            return None
        with self._lock:
            self._cleanup_locked()
            record = self._records.get(request_id)
            return record.snapshot() if record is not None else None

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def _set_status(self, request_id: str, *, status: str, stage: str, detail: str) -> dict[str, Any]:
        request_id = _clean_text(request_id)
        if not request_id:
            return {}
        with self._lock:
            self._cleanup_locked()
            record = self._records.get(request_id)
            if record is None:
                record = AgentProgressRecord(
                    request_id=request_id,
                    expires_at=time.time() + self.ttl_seconds,
                )
                self._records[request_id] = record
            now = _now_iso()
            record.status = status
            record.stage = stage
            record.detail = detail
            record.updated_at = now
            record.expires_at = time.time() + self.ttl_seconds
            record.events.append({
                "type": status,
                "stage": stage,
                "detail": detail,
                "at": now,
                "data": {},
            })
            visible_event = _visible_status_event(status, stage, detail, now)
            if visible_event is not None:
                if not _has_visible_event(record.visible_events, visible_event):
                    record.visible_events.append(visible_event)
                record.visible_stage = visible_event["stage"]
                record.visible_detail = visible_event["detail"]
                if status not in {"running"}:
                    work_trace_item = _work_trace_item_from_visible(visible_event, item_type="status")
                    if work_trace_item is not None and not _has_work_trace_item(record.work_trace_items, work_trace_item):
                        record.work_trace_items.append(work_trace_item)
            if len(record.events) > self.max_events:
                record.events = record.events[-self.max_events :]
            if len(record.visible_events) > self.max_events:
                record.visible_events = record.visible_events[-self.max_events :]
            if len(record.work_trace_items) > self.max_events:
                record.work_trace_items = record.work_trace_items[-self.max_events :]
            return record.snapshot()

    def _finish(self, request_id: str, *, status: str, stage: str, detail: str) -> dict[str, Any]:
        request_id = _clean_text(request_id)
        if not request_id:
            return {}
        with self._lock:
            self._cleanup_locked()
            record = self._records.get(request_id)
            if record is None:
                record = AgentProgressRecord(
                    request_id=request_id,
                    expires_at=time.time() + self.ttl_seconds,
                )
                self._records[request_id] = record
            now = _now_iso()
            record.status = status
            record.stage = stage
            record.detail = detail
            record.updated_at = now
            record.expires_at = time.time() + self.ttl_seconds
            if not record.events or record.events[-1].get("detail") != detail:
                record.events.append({
                    "type": status,
                    "stage": stage,
                    "detail": detail,
                    "at": now,
                    "data": {},
                })
                visible_event = _visible_status_event(status, stage, detail, now)
                if visible_event is not None:
                    record.visible_events.append(visible_event)
                    record.visible_stage = visible_event["stage"]
                    record.visible_detail = visible_event["detail"]
                    work_trace_item = _work_trace_item_from_visible(visible_event, item_type="status")
                    if work_trace_item is not None and not _has_work_trace_item(record.work_trace_items, work_trace_item):
                        record.work_trace_items.append(work_trace_item)
                if len(record.events) > self.max_events:
                    record.events = record.events[-self.max_events :]
                if len(record.visible_events) > self.max_events:
                    record.visible_events = record.visible_events[-self.max_events :]
                if len(record.work_trace_items) > self.max_events:
                    record.work_trace_items = record.work_trace_items[-self.max_events :]
            return record.snapshot()

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired = [request_id for request_id, record in self._records.items() if record.expires_at < now]
        for request_id in expired:
            del self._records[request_id]


def unknown_progress_snapshot(request_id: str) -> dict[str, Any]:
    return {
        "requestId": _clean_text(request_id),
        "status": "unknown",
        "stage": "waiting",
        "detail": "Waiting for agent progress...",
        "visibleStage": "waiting",
        "visibleDetail": "Waiting for agent progress...",
        "createdAt": "",
        "updatedAt": "",
        "events": [],
        "visibleEvents": [],
        "workTrace": {"status": "unknown", "items": []},
    }


# ---------------------------------------------------------------------------
# AgentEvent -> progress event conversion
#
# These helpers convert internal AgentEvent objects into three UI-facing views:
# raw progress events, filtered visible events, and compact work-trace items.
# ---------------------------------------------------------------------------

def _progress_event(event: AgentEvent) -> dict[str, Any]:
    stage, detail = _stage_and_detail(event)
    return {
        "type": event.type,
        "stage": stage,
        "detail": detail,
        "at": _now_iso(),
        "data": dict(event.data),
    }


def _visible_progress_event(event: AgentEvent, progress_event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = _clean_text(event.type)
    data = event.data or {}
    if event_type == "model_response":
        detail = _provider_native_web_search_detail(data)
        if not detail:
            return None
    elif event_type in {"model_request", "model_delta", "completed"}:
        return None
    elif event_type in {"work_trace_delta", "work_trace_item"}:
        detail = _clean_text(data.get("text") or event.message)
        if not detail:
            return None
    elif event_type == "tool_call":
        name = _clean_text(data.get("name")) or "tool"
        detail = _visible_tool_start_detail(name, data)
    elif event_type == "tool_result":
        detail = _visible_tool_result_detail(_clean_text(data.get("name")) or "tool", data)
        if not detail:
            return None
    elif event_type == "tool_error":
        detail = f"Tool failed: {_clean_text(data.get('name')) or 'tool'}"
    elif event_type == "tool_approval_requested":
        name = _clean_text(data.get("toolName") or data.get("tool_name")) or "tool"
        detail = f"Approval needed for {name}."
    elif event_type == "tool_approval_resolved":
        return None
    elif event_type in {"context_compressing", "context_compressed", "context_overflow"}:
        detail = progress_event["detail"]
    elif event_type in {"tool_calls_pending", "halted", "tool_halted", "cancelled"}:
        detail = progress_event["detail"]
    else:
        detail = _clean_text(event.message)
        if not detail or detail in {"Calling model provider.", "Model response received.", "Agent run completed."}:
            return None
    return {
        "type": event_type,
        "stage": progress_event["stage"],
        "detail": detail,
        "at": progress_event["at"],
        "data": dict(data),
    }


def _work_trace_item(
    event: AgentEvent,
    progress_event: dict[str, Any],
    visible_event: dict[str, Any] | None,
) -> dict[str, Any] | None:
    event_type = _clean_text(event.type)
    data = event.data or {}
    if event_type == "work_trace_item":
        text = _clean_text(data.get("text") or event.message)
        if not text:
            return None
        return {
            "type": _clean_text(data.get("trace_type")) or "summary",
            "text": text,
            "at": progress_event["at"],
            "source": _clean_text(data.get("source")) or "provider",
            "complete": True,
        }
    if event_type == "work_trace_delta":
        text = _clean_text(data.get("text") or event.message)
        if not text:
            return None
        return {
            "type": _clean_text(data.get("trace_type")) or "summary",
            "text": text,
            "at": progress_event["at"],
            "source": _clean_text(data.get("source")) or "provider",
            "complete": False,
        }
    if visible_event is None:
        return None
    if event_type == "model_response" and _provider_native_web_search_detail(data):
        return _work_trace_item_from_visible(visible_event, item_type="tool", source="provider", complete=True)
    if event_type in {"tool_call", "tool_result", "tool_error"}:
        name = _clean_text(data.get("name"))
        return _work_trace_item_from_visible(visible_event, item_type="skill" if _is_skill_tool(name) else "tool")
    if event_type in {"tool_approval_requested", "tool_calls_pending", "halted", "tool_halted", "cancelled"}:
        return _work_trace_item_from_visible(visible_event, item_type="status")
    return None


def _work_trace_item_from_visible(
    visible_event: dict[str, Any],
    *,
    item_type: str,
    source: str = "runtime",
    complete: bool | None = None,
) -> dict[str, Any] | None:
    text = _clean_text(visible_event.get("detail"))
    if not text:
        return None
    item = {
        "type": item_type,
        "text": text,
        "at": _clean_text(visible_event.get("at")),
        "source": source,
    }
    if complete is not None:
        item["complete"] = bool(complete)
    return item


# ---------------------------------------------------------------------------
# Event de-duplication and work-trace merging
# ---------------------------------------------------------------------------

def _has_visible_event(events: list[dict[str, Any]], event: dict[str, Any]) -> bool:
    key = (_clean_text(event.get("type")), _clean_text(event.get("detail")))
    return any((_clean_text(item.get("type")), _clean_text(item.get("detail"))) == key for item in events)


def _has_work_trace_item(items: list[dict[str, Any]], item: dict[str, Any]) -> bool:
    key = (_clean_text(item.get("type")), _clean_text(item.get("text")))
    return any((_clean_text(existing.get("type")), _clean_text(existing.get("text"))) == key for existing in items)


def _merge_work_trace_item(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    item_type = _clean_text(item.get("type")) or "summary"
    item_source = _clean_text(item.get("source"))
    item_text = _clean_text(item.get("text"))
    if not item_text:
        return
    for index in range(len(items) - 1, -1, -1):
        existing = items[index]
        if (_clean_text(existing.get("type")) or "summary") != item_type:
            continue
        if _clean_text(existing.get("source")) != item_source:
            continue
        existing_text = _clean_text(existing.get("text"))
        if existing_text == item_text or item_text.startswith(existing_text) or existing_text.startswith(item_text):
            items[index] = {**item, "text": item_text}
            return
    if not _has_work_trace_item(items, item):
        items.append({**item, "text": item_text})


def _public_work_trace_item(item: dict[str, Any]) -> dict[str, Any]:
    public = dict(item)
    if not (public.get("type") == "tool" and public.get("complete") is True):
        public.pop("complete", None)
    return public


def _visible_status_event(status: str, stage: str, detail: str, at: str) -> dict[str, Any] | None:
    if status == "completed":
        return None
    return {
        "type": status,
        "stage": stage,
        "detail": detail,
        "at": at,
        "data": {},
    }


# ---------------------------------------------------------------------------
# Event type -> stage/detail mapping
#
# This is the central display dictionary for progress. Add new AgentEvent types
# here when the runtime starts emitting them.
# ---------------------------------------------------------------------------

def _stage_and_detail(event: AgentEvent) -> tuple[str, str]:
    data = event.data or {}
    event_type = _clean_text(event.type)
    if event_type == "context_compressing":
        return "thinking", "Compacting context"
    if event_type == "context_compressed":
        before_count = int(data.get("before_message_count") or 0)
        after_count = int(data.get("after_message_count") or 0)
        if before_count and after_count:
            return "thinking", f"Compressed context: {before_count} -> {after_count} messages."
        return "thinking", "Compressed long context."
    if event_type == "context_overflow":
        return "thinking", "Context too large; compressing and retrying."
    if event_type == "model_request":
        return "thinking", "Calling model provider."
    if event_type == "model_response":
        native_web_search_detail = _provider_native_web_search_detail(data)
        if native_web_search_detail:
            return "tool", native_web_search_detail
        count = int(data.get("tool_call_count") or 0)
        if count:
            suffix = "s" if count != 1 else ""
            return "planning", f"Model requested {count} tool call{suffix}."
        return "thinking", "Model response received."
    if event_type in {"work_trace_delta", "work_trace_item"}:
        text = _clean_text(data.get("text") or event.message)
        trace_type = _clean_text(data.get("trace_type")) or "summary"
        return "thinking", text or f"Received {trace_type}."
    if event_type == "tool_call":
        name = _clean_text(data.get("name")) or "tool"
        return "tool", _tool_start_detail(name, data)
    if event_type == "tool_result":
        name = _clean_text(data.get("name")) or "tool"
        return "tool", _tool_result_detail(name, data)
    if event_type == "tool_error":
        name = _clean_text(data.get("name")) or "tool"
        return "tool", f"Tool failed: {name}"
    if event_type == "tool_warning":
        name = _clean_text(data.get("tool_name")) or "tool"
        return "tool", f"Tool warning: {name}"
    if event_type == "tool_approval_requested":
        name = _clean_text(data.get("toolName") or data.get("tool_name")) or "tool"
        return "approval", f"Approval needed: {name}"
    if event_type == "tool_approval_resolved":
        name = _clean_text(data.get("toolName") or data.get("tool_name")) or "tool"
        status = _clean_text(data.get("status")) or "resolved"
        return "approval", f"Approval {status}: {name}"
    if event_type == "tool_approval_reused":
        name = _clean_text(data.get("toolName") or data.get("tool_name")) or "tool"
        return "tool", f"Approval reused: {name}"
    if event_type == "tool_blocked":
        name = _clean_text(data.get("tool_name")) or "tool"
        return "tool", f"Tool blocked: {name}"
    if event_type == "tool_halted":
        name = _clean_text(data.get("tool_name")) or "tool"
        return "halted", f"Tool loop stopped: {name}"
    if event_type == "completed":
        return "completed", "Agent run completed."
    if event_type == "cancelled":
        return "cancelled", "Agent run cancelled."
    if event_type == "tool_calls_pending":
        return "pending", "Tool calls are waiting for an executor."
    if event_type == "halted":
        return "halted", "Maximum agent turns reached."
    return event_type or "working", _clean_text(event.message) or "Working..."


def _provider_native_web_search_detail(data: dict[str, Any]) -> str:
    call_count = _positive_int(data.get("web_search_call_count"))
    if not call_count:
        return ""
    source_count = _positive_int(data.get("web_search_source_count"))
    search_label = "search" if call_count == 1 else "searches"
    count_text = f"{call_count} {search_label}"
    if source_count:
        source_label = "source" if source_count == 1 else "sources"
        count_text = f"{count_text}, {source_count} {source_label}"
    query_text = _web_search_query_summary(data.get("web_search_queries") or data.get("webSearchQueries"))
    if query_text:
        return f"Searched the web: {query_text} ({count_text})."
    return f"Searched the web: {count_text}."


# ---------------------------------------------------------------------------
# Status and text helpers
# ---------------------------------------------------------------------------

def _web_search_query_summary(value: Any) -> str:
    queries = value if isinstance(value, list) else []
    parts: list[str] = []
    for item in queries:
        text = _clean_text(item)
        if not text:
            continue
        if len(text) > 96:
            text = f"{text[:95]}…"
        parts.append(f'"{text}"')
        if len(parts) >= 3:
            break
    if not parts:
        return ""
    remaining = len(queries) - len(parts)
    return "; ".join(parts) + (f"; +{remaining} more" if remaining > 0 else "")


def _positive_int(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _status_for_event(event: AgentEvent) -> str | None:
    if event.type == "completed":
        return "completed"
    if event.type == "cancelled":
        return "cancelled"
    if event.type == "halted":
        return "stopped"
    if event.type == "tool_halted":
        return "stopped"
    if event.type == "tool_calls_pending":
        return "pending"
    if event.type == "tool_approval_requested":
        return "waiting"
    return "running"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


# ---------------------------------------------------------------------------
# Tool progress wording
#
# The detailed wording is used in raw progress history; the visible wording is
# shorter and optimized for the UI's live status/work-trace display.
# ---------------------------------------------------------------------------

def _tool_start_detail(name: str, data: dict[str, Any]) -> str:
    args = _tool_args(data.get("arguments"))
    note_id = _clean_text(args.get("note_id") or args.get("id"))
    heading = _clean_text(args.get("heading"))
    if name == "skills_list":
        category = _clean_text(args.get("category"))
        return f"Checking available skills{f' in category {category}' if category else ''}."
    if name == "skill_view":
        skill_name = _clean_text(args.get("name"))
        file_path = _clean_text(args.get("file_path") or args.get("filePath"))
        target = skill_name or "skill instructions"
        return f"Loading skill: {target}{f' -> {file_path}' if file_path else ''}."
    if name == "search_notes":
        query = _clean_text(args.get("query"))
        return f"Searching paper notes{f': {query}' if query else ''}."
    if name == "get_note_context":
        return f"Reading note context{f' for {note_id}' if note_id else ''}."
    if name == "create_image_artifact":
        return "Generating image."
    if name == "read_paper":
        return read_paper_progress_detail(args, suffix=".")
    if name == "review_note":
        action = _clean_text(args.get("action") or "validate_html")
        return f"Reviewing note ({action}){f' for {note_id}' if note_id else ''}."
    if name == "write_note":
        action = _clean_text(args.get("action"))
        target = f": {heading}" if heading else ""
        note = f" in {note_id}" if note_id else ""
        return f"Updating paper note{target}{note}{f' ({action})' if action else ''}."
    if name == "manage_annotations":
        action = _clean_text(args.get("action"))
        note = f" in {note_id}" if note_id else ""
        return f"Updating annotation{note}{f' ({action})' if action else ''}."
    if name == "write_note_media":
        action = _clean_text(args.get("action"))
        target = f": {heading}" if heading else ""
        note = f" in {note_id}" if note_id else ""
        return f"Updating note media{target}{note}{f' ({action})' if action else ''}."
    if name in {"write_note_section", "append_note_section", "replace_note_section"}:
        action = "Writing" if name != "replace_note_section" else "Replacing"
        target = f": {heading}" if heading else ""
        note = f" in {note_id}" if note_id else ""
        return f"{action} note section{target}{note}."
    if name == "update_note_metadata":
        return f"Updating note metadata{f' for {note_id}' if note_id else ''}."
    if name == "read_note_html":
        return f"Reading note HTML{f' for {note_id}' if note_id else ''}."
    if name == "list_note_sections":
        return f"Reading note outline{f' for {note_id}' if note_id else ''}."
    return f"Running tool: {name}{_argument_suffix(args)}"


def _visible_tool_start_detail(name: str, data: dict[str, Any]) -> str:
    args = _tool_args(data.get("arguments"))
    if name == "skills_list":
        category = _clean_text(args.get("category"))
        return f"Checking available skills{f' in category {category}' if category else ''}..."
    if name == "skill_view":
        skill_name = _clean_text(args.get("name"))
        file_path = _clean_text(args.get("file_path") or args.get("filePath"))
        target = skill_name or "skill instructions"
        return f"Loading skill: {target}{f' -> {file_path}' if file_path else ''}..."
    if name == "search_notes":
        query = _clean_text(args.get("query"))
        return f"Searching paper notes{f': {query}' if query else ''}..."
    if name == "get_note_context":
        return "Reading note context..."
    if name == "create_image_artifact":
        return "Generating image..."
    if name == "read_paper":
        return read_paper_progress_detail(args)
    if name == "review_note":
        return "Reviewing note..."
    if name == "write_note":
        return "Updating note..."
    if name == "manage_annotations":
        return "Updating annotation..."
    if name == "write_note_media":
        return "Updating note media..."
    if name in {"write_note_section", "append_note_section", "replace_note_section"}:
        return "Updating note content..."
    if name == "update_note_metadata":
        return "Updating note metadata..."
    if name == "read_note_html":
        return "Reading note HTML..."
    if name == "list_note_sections":
        return "Reading note outline..."
    if name == "persistent_memory":
        return "Checking saved memory..."
    if name == "session_search":
        return "Searching past sessions..."
    if name == "todo":
        return "Updating task list..."
    if name == "web_search":
        return "Searching the web..."
    if name == "web_fetch":
        return "Reading web page..."
    return f"Using {name}{_argument_suffix(args)}..."


def _tool_result_detail(name: str, data: dict[str, Any]) -> str:
    message = _clean_text(data.get("message"))
    if message:
        return message
    snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else {}
    changed_files = snapshot.get("changedFiles") if isinstance(snapshot.get("changedFiles"), list) else []
    if changed_files:
        count = len(changed_files)
        suffix = "s" if count != 1 else ""
        return f"Tool completed: {name}; {count} file{suffix} changed."
    return f"Tool completed: {name}"


def _visible_tool_result_detail(name: str, data: dict[str, Any]) -> str:
    snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else {}
    changed_files = snapshot.get("changedFiles") if isinstance(snapshot.get("changedFiles"), list) else []
    if changed_files:
        count = len(changed_files)
        suffix = "s" if count != 1 else ""
        return f"Saved {count} file{suffix}."
    return ""


# ---------------------------------------------------------------------------
# Argument parsing and compact value formatting
# ---------------------------------------------------------------------------

def _tool_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _is_skill_tool(name: str) -> bool:
    return name in {"skills_list", "skill_view"}


def _argument_suffix(args: dict[str, Any]) -> str:
    formatted = _format_arguments(args)
    return f" ({formatted})" if formatted else ""


def _format_arguments(args: dict[str, Any], *, max_items: int = 4, max_chars: int = 140) -> str:
    if not isinstance(args, dict) or not args:
        return ""
    parts: list[str] = []
    for key in sorted(args):
        value = args.get(key)
        if value in (None, "", [], {}):
            continue
        parts.append(f"{key}: {_short_value(value)}")
        if len(parts) >= max_items:
            break
    text = ", ".join(parts)
    return f"{text[:max_chars - 1]}…" if len(text) > max_chars else text


def _short_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return f"[{', '.join(_short_value(item) for item in value[:3])}{', …' if len(value) > 3 else ''}]"
    if isinstance(value, dict):
        return "{…}"
    text = _clean_text(value).replace("\n", " ")
    if len(text) > 46:
        text = f"{text[:45]}…"
    return json.dumps(text, ensure_ascii=False)
