from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from agent_runtime.messages import (
    content_text,
    json_safe,
    merge_existing_transcript_fields,
    messages_to_transcript,
    request_message_content,
)
from agent_runtime.streaming import AgentStreamEvent, provider_reasoning_event_from_message


ACTIVE_RUN_METADATA_KEY = "activeRun"


def request_id(request: Any) -> str:
    return str(request.metadata.get("requestId") or request.metadata.get("request_id") or "").strip()


def active_run_metadata(
    request: Any,
    *,
    provider: str,
    model: str,
    status: str,
) -> dict[str, Any]:
    current_request_id = request_id(request)
    if not current_request_id:
        return {}
    started_at = isoformat_utc(now_utc())
    message = content_text(request_message_content(request)).strip()
    return {
        "requestId": current_request_id,
        "status": status,
        "startedAt": started_at,
        "provider": provider,
        "model": model,
        "noteId": request.note_id or "",
        "message": message[:500],
        "progress": active_run_progress_payload(current_request_id, status=status, events=[]),
    }


def active_run_for_request(session: Any | None, current_request_id: str) -> dict[str, Any]:
    if session is None:
        return {}
    metadata = session.metadata.metadata if isinstance(session.metadata.metadata, dict) else {}
    active_run = metadata.get(ACTIVE_RUN_METADATA_KEY)
    if not isinstance(active_run, dict):
        return {}
    if str(active_run.get("requestId") or active_run.get("request_id") or "").strip() != current_request_id:
        return {}
    return active_run


def active_run_progress_payload(
    current_request_id: str,
    *,
    status: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    visible_events = [
        {
            "stage": str(event.get("stage") or event.get("type") or "").strip(),
            "detail": str(event.get("message") or "").strip(),
            "at": str(event.get("at") or "").strip(),
        }
        for event in events
        if str(event.get("message") or "").strip()
    ]
    work_items = [
        {
            "type": str(event.get("stage") or event.get("type") or "status").strip() or "status",
            "text": str(event.get("message") or "").strip(),
            "at": str(event.get("at") or "").strip(),
            "source": str((event.get("data") if isinstance(event.get("data"), dict) else {}).get("source") or "runtime"),
            "data": event.get("data") if isinstance(event.get("data"), dict) else {},
            "complete": run_trace_event_work_item_complete(event),
        }
        for event in events
        if str(event.get("message") or "").strip()
    ]
    detail = visible_events[-1]["detail"] if visible_events else "Starting agent run."
    stage = visible_events[-1]["stage"] if visible_events else "starting"
    return {
        "requestId": current_request_id,
        "status": status,
        "stage": stage or status,
        "detail": detail,
        "visibleEvents": visible_events,
        "events": list(events),
        "workTrace": {"status": status, "items": work_items},
    }


def run_trace_event_work_item_complete(event: dict[str, Any]) -> bool:
    if str(event.get("type") or "").strip() == "work_trace_delta":
        return False
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    for payload in (nested, data):
        if payload.get("statusComplete") is False or payload.get("complete") is False:
            return False
        if payload.get("statusComplete") is True or payload.get("complete") is True:
            return True
    return True


def is_provider_reasoning_stream_event(event: AgentStreamEvent) -> bool:
    if event.event not in {"work_trace_item", "work_trace_delta"}:
        return False
    trace_type = str(event.data.get("traceType") or event.data.get("trace_type") or "").strip()
    if trace_type not in {"reasoning", "summary"}:
        return False
    data = event.data.get("data") if isinstance(event.data.get("data"), dict) else {}
    detail_type = str(data.get("type") or "").strip()
    return detail_type in {"reasoning", "reasoning_summary"} or str(event.data.get("source") or "").strip() in {
        "deepseek",
        "openai",
        "codex",
        "provider",
    }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def stamp_stream_event(event: AgentStreamEvent) -> None:
    event.data = dict(event.data)
    event.data.setdefault("at", isoformat_utc(now_utc()))


def run_trace_event_from_stream_event(event: AgentStreamEvent) -> dict[str, Any] | None:
    if event.event not in {"work_trace_item", "work_trace_delta"}:
        return None
    data = dict(event.data)
    message = str(data.get("text") or data.get("delta") or "").strip()
    if not message:
        return None
    return {
        "type": event.event,
        "stage": str(data.get("traceType") or data.get("trace_type") or "").strip(),
        "message": message,
        "at": str(data.get("at") or "").strip(),
        "data": json_safe(data),
    }


def run_trace_has_equivalent_event(events: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    candidate_message = str(candidate.get("message") or "").strip()
    candidate_stage = str(candidate.get("stage") or "").strip()
    candidate_source = str((candidate.get("data") if isinstance(candidate.get("data"), dict) else {}).get("source") or "").strip()
    for event in events:
        message = str(event.get("message") or "").strip()
        stage = str(event.get("stage") or "").strip()
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        source = str(data.get("source") or "").strip()
        if message == candidate_message and stage == candidate_stage and source == candidate_source:
            return True
    return False


def new_messages_for_current_run(
    final_messages: list[BaseMessage],
    input_messages: list[BaseMessage],
) -> list[BaseMessage]:
    if len(final_messages) > len(input_messages):
        return final_messages[len(input_messages):]
    return final_messages[-1:] if final_messages else []


def model_response_trace_events(messages: list[BaseMessage], *, at: datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for turn, message in enumerate(messages, start=1):
        if not isinstance(message, AIMessage):
            continue
        web_search_data = web_search_trace_data_from_message(message)
        if not web_search_data:
            continue
        call_count = int(web_search_data.get("web_search_call_count") or 0)
        source_count = int(web_search_data.get("web_search_source_count") or 0)
        source_text = (
            f" and {source_count} source{'s' if source_count != 1 else ''}"
            if source_count
            else ""
        )
        events.append({
            "type": "model_response",
            "stage": "model_response",
            "message": (
                "Model provider returned a response with "
                f"{call_count} web search call{'s' if call_count != 1 else ''}"
                f"{source_text}."
            ),
            "at": isoformat_utc(at),
            "data": {
                "turn": turn,
                "source": message_provider_name(message),
                **web_search_data,
            },
        })
    return events


def web_search_trace_data_from_message(message: AIMessage) -> dict[str, Any]:
    calls: list[Any] = []
    sources: list[dict[str, str]] = []
    queries: list[str] = []
    seen_urls: set[str] = set()
    content_blocks = message_content_blocks(message)
    for block in content_blocks:
        collect_web_search_trace_from_block(block, calls=calls, sources=sources, queries=queries, seen_urls=seen_urls)
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        for item in additional_kwargs.get("tool_outputs") or []:
            collect_web_search_trace_from_block(item, calls=calls, sources=sources, queries=queries, seen_urls=seen_urls)
    if not calls:
        return {}
    data: dict[str, Any] = {"web_search_call_count": len(calls)}
    if sources:
        data["web_search_source_count"] = len(sources)
    if queries:
        data["web_search_queries"] = queries[:6]
    return data


def message_content_blocks(message: AIMessage) -> list[Any]:
    content = getattr(message, "content", None)
    return content if isinstance(content, list) else []


def collect_web_search_trace_from_block(
    block: Any,
    *,
    calls: list[Any],
    sources: list[dict[str, str]],
    queries: list[str],
    seen_urls: set[str],
) -> None:
    if not isinstance(block, dict):
        return
    block_type = str(block.get("type") or "").strip()
    name = str(block.get("name") or "").strip()
    if block_type == "web_search_call" or (block_type == "server_tool_use" and name == "web_search"):
        calls.append(block)
        collect_web_search_queries(block, queries, set(queries), depth=0)
        collect_sources_from_value(block, sources=sources, seen_urls=seen_urls)
    if block_type == "web_search_tool_result":
        collect_sources_from_value(block, sources=sources, seen_urls=seen_urls)
    for annotation in block.get("annotations") or []:
        collect_source_from_mapping(annotation, sources=sources, seen_urls=seen_urls)


def collect_sources_from_value(value: Any, *, sources: list[dict[str, str]], seen_urls: set[str], depth: int = 0) -> None:
    if depth > 5:
        return
    if isinstance(value, dict):
        collect_source_from_mapping(value, sources=sources, seen_urls=seen_urls)
        for item in value.values():
            collect_sources_from_value(item, sources=sources, seen_urls=seen_urls, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            collect_sources_from_value(item, sources=sources, seen_urls=seen_urls, depth=depth + 1)


def collect_source_from_mapping(value: dict[str, Any], *, sources: list[dict[str, str]], seen_urls: set[str]) -> None:
    url = str(value.get("url") or value.get("uri") or "").strip()
    if not url or url in seen_urls:
        return
    seen_urls.add(url)
    sources.append({
        "title": str(value.get("title") or "").strip(),
        "url": url,
        "snippet": str(value.get("snippet") or value.get("text") or "").strip(),
    })


def collect_web_search_queries(value: Any, queries: list[str], seen: set[str], *, depth: int) -> None:
    if depth > 4 or len(queries) >= 6:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip()
            if normalized_key in {"query", "queries", "search_query", "searchQuery", "webSearchQueries", "web_search_queries"}:
                append_web_search_query(item, queries, seen)
                if len(queries) >= 6:
                    return
                continue
            collect_web_search_queries(item, queries, seen, depth=depth + 1)
            if len(queries) >= 6:
                return
        return
    if isinstance(value, list):
        for item in value:
            collect_web_search_queries(item, queries, seen, depth=depth + 1)
            if len(queries) >= 6:
                return


def append_web_search_query(value: Any, queries: list[str], seen: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            append_web_search_query(item, queries, seen)
            if len(queries) >= 6:
                return
        return
    if isinstance(value, dict):
        collect_web_search_queries(value, queries, seen, depth=0)
        return
    text = " ".join(str(value or "").split())
    if not text:
        return
    if len(text) > 160:
        text = f"{text[:159]}..."
    key = text.casefold()
    if key in seen:
        return
    seen.add(key)
    queries.append(text)


def message_provider_name(message: AIMessage) -> str:
    metadata = getattr(message, "response_metadata", None)
    if isinstance(metadata, dict):
        provider = str(metadata.get("model_provider") or "").strip()
        if provider:
            return provider
    return "provider"


def work_trace_events_from_messages(
    messages: list[BaseMessage],
    *,
    include_provider_reasoning: bool = True,
) -> list[AgentStreamEvent]:
    events: list[AgentStreamEvent] = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        metadata = getattr(message, "response_metadata", None)
        trace_items: list[Any] = []
        if isinstance(metadata, dict):
            trace_keys = ["codex_work_trace"]
            if include_provider_reasoning:
                trace_keys.append("codex_model_trace")
            for key in trace_keys:
                value = metadata.get(key)
                if isinstance(value, list):
                    trace_items.extend(value)
        for item in trace_items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("delta") or "").strip()
            if not text:
                continue
            events.append(AgentStreamEvent("work_trace_item", {
                "text": text,
                "traceType": str(item.get("traceType") or item.get("trace_type") or "summary"),
                "source": str(item.get("source") or "codex"),
                "data": json_safe(item.get("data") if isinstance(item.get("data"), dict) else item),
            }))
        reasoning_event = provider_reasoning_event_from_message(message) if include_provider_reasoning else None
        if reasoning_event is not None:
            events.append(reasoning_event)
    return dedupe_work_trace_events(events)


def dedupe_work_trace_events(events: list[AgentStreamEvent]) -> list[AgentStreamEvent]:
    deduped: list[AgentStreamEvent] = []
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        key = (
            str(event.data.get("traceType") or ""),
            str(event.data.get("source") or ""),
            str(event.data.get("text") or event.data.get("delta") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def run_trace_payload(
    request: Any,
    *,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    duration_ms = max(0, round((finished_at - started_at).total_seconds() * 1000))
    current_request_id = request_id(request)
    return {
        "requestId": current_request_id,
        "startedAt": isoformat_utc(started_at),
        "finishedAt": isoformat_utc(finished_at),
        "durationMs": duration_ms,
        "status": status,
        "events": list(events),
    }


def with_assistant_run_trace(messages: list[dict[str, Any]], run_trace: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not run_trace:
        return messages
    updated = [dict(message) for message in messages]
    for index in range(len(updated) - 1, -1, -1):
        if updated[index].get("role") == "assistant":
            updated[index]["runTrace"] = copy.deepcopy(run_trace)
            break
    return updated


def persist_active_run(
    session_store: Any,
    session: Any,
    request: Any,
    *,
    input_messages: list[BaseMessage],
    provider: str,
    model: str,
) -> Any:
    transcript = messages_to_transcript(input_messages)
    transcript = merge_existing_transcript_fields(transcript, session.messages)
    persisted = session_store.replace_messages(session.metadata.session_id, transcript)
    metadata = active_run_metadata(
        request,
        provider=provider,
        model=model,
        status="running",
    )
    if metadata:
        session_store.update_session_metadata(session.metadata.session_id, {ACTIVE_RUN_METADATA_KEY: metadata})
        persisted = session_store.require_session(session.metadata.session_id)
    return persisted


def update_active_run_progress(
    session_store: Any,
    session_id: str,
    request: Any,
    *,
    events: list[dict[str, Any]],
    status: str,
) -> None:
    current_request_id = request_id(request)
    if not current_request_id:
        return
    current = session_store.get_session(session_id)
    active_run = active_run_for_request(current, current_request_id)
    if not active_run:
        return
    active_run = dict(active_run)
    active_run["status"] = status
    active_run["progress"] = active_run_progress_payload(current_request_id, status=status, events=events)
    session_store.update_session_metadata(session_id, {ACTIVE_RUN_METADATA_KEY: active_run})


def finish_active_run(
    session_store: Any,
    session_id: str,
    request: Any,
    *,
    status: str,
    error_text: str = "",
) -> None:
    current_request_id = request_id(request)
    if not current_request_id:
        return
    current = session_store.get_session(session_id)
    active_run = active_run_for_request(current, current_request_id)
    if not active_run:
        return
    metadata = dict(current.metadata.metadata)
    if status == "completed":
        metadata.pop(ACTIVE_RUN_METADATA_KEY, None)
    else:
        failed = dict(active_run)
        failed["status"] = status
        failed["finishedAt"] = isoformat_utc(now_utc())
        if error_text:
            failed["error"] = error_text
        metadata[ACTIVE_RUN_METADATA_KEY] = failed
    session_store.update_session_metadata(session_id, metadata, replace=True)


def context_compaction_trace_event(
    event_type: str,
    message: str,
    *,
    at: datetime,
    session_id: str,
    provider: str,
    model: str,
    focus: str | None = None,
) -> dict[str, Any]:
    return {
        "type": event_type,
        "stage": event_type,
        "message": message,
        "at": isoformat_utc(at),
        "data": {
            "sessionId": session_id,
            "provider": provider,
            "model": model,
            "focus": str(focus or "").strip(),
        },
    }


__all__ = [
    "ACTIVE_RUN_METADATA_KEY",
    "active_run_for_request",
    "active_run_metadata",
    "active_run_progress_payload",
    "context_compaction_trace_event",
    "is_provider_reasoning_stream_event",
    "isoformat_utc",
    "model_response_trace_events",
    "new_messages_for_current_run",
    "now_utc",
    "finish_active_run",
    "persist_active_run",
    "request_id",
    "run_trace_event_from_stream_event",
    "run_trace_has_equivalent_event",
    "run_trace_payload",
    "stamp_stream_event",
    "update_active_run_progress",
    "with_assistant_run_trace",
    "work_trace_events_from_messages",
]
