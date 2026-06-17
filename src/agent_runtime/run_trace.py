from __future__ import annotations

import copy
import json
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from agent_runtime.messages import (
    content_text,
    json_safe,
    merge_existing_transcript_fields,
    messages_to_transcript,
    request_message_content,
)

__all__ = [
    "AgentStreamEvent",
    "LANGCHAIN_AGENT_STREAM_MODES",
    "attach_run_trace_to_latest_assistant",
    "build_model_response_trace_events",
    "finish_active_run_metadata",
    "is_provider_reasoning_trace_event",
    "now_utc",
    "provider_reasoning_event_from_message",
    "record_stream_event_in_active_run",
    "save_active_run_metadata",
    "stream_events_from_langchain_chunk",
    "stream_final_trace_events_and_build_run_trace",
]

ACTIVE_RUN_METADATA_KEY = "activeRun"
LANGCHAIN_AGENT_STREAM_MODES = ["messages", "updates", "values", "custom"]
PROVIDER_TRACE_BLOCK_TYPES = {"commentary": "commentary", "summary": "summary",}
RAW_PROVIDER_REASONING_BLOCK_TYPES = {"reasoning", "thinking", "thought"}


# 公开流式事件 API
@dataclass(slots=True)
class AgentStreamEvent:
    """表示一条标准化后的 agent stream 事件，通常会通过 SSE 发给前端。"""

    event: str
    data: dict[str, Any]


def stream_events_from_langchain_chunk(chunk: Any) -> list[AgentStreamEvent]:
    """把 LangChain stream chunk 转成前端可以通过 SSE 消费的事件列表。"""
    mode = str(chunk.get("type") or "").strip() if isinstance(chunk, dict) else ""
    if mode == "messages":
        return _events_from_messages_chunk(chunk)
    if mode == "updates":
        return _events_from_updates_chunk(chunk)
    if mode == "custom":
        return _events_from_custom_chunk(chunk)
    return []


# LangChain chunk 处理
def _events_from_messages_chunk(chunk: Any) -> list[AgentStreamEvent]:
    """处理 LangChain messages 模式中的模型 token chunk，并转成前端事件。"""
    data = chunk.get("data") if isinstance(chunk, dict) else None
    if not isinstance(data, tuple | list) or len(data) < 2:
        return []
    token, metadata = data[0], data[1]
    if isinstance(metadata, dict):
        node = str(metadata.get("langgraph_node") or "").strip()
        if node and node != "model":
            return []

    trace = getattr(token, "response_metadata", None)
    trace = trace.get("paper_notes_trace") if isinstance(trace, dict) else None
    if isinstance(trace, dict):
        event = _trace_event_from_payload(trace)
        if event:
            return [event]
    if isinstance(trace, list):
        events = [event for item in trace if isinstance(item, dict) if (event := _trace_event_from_payload(item))]
        if events:
            return events

    provider = _message_provider(token)
    content_blocks = getattr(token, "content_blocks", None)
    if isinstance(content_blocks, list):
        events: list[AgentStreamEvent] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "non_standard" and isinstance(block.get("value"), dict):
                block = block["value"]
            raw_type = str(block.get("type") or "").strip()
            block_type = PROVIDER_TRACE_BLOCK_TYPES.get(raw_type) or ""
            if not block_type:
                summary = _summary_text(block.get("summary"))
                if raw_type in RAW_PROVIDER_REASONING_BLOCK_TYPES and summary:
                    block_type = "summary"
                elif raw_type == "reasoning" and provider == "openai" and _first_text(block.get("reasoning")):
                    block_type = "summary"
            if not block_type:
                continue
            if block_type == "summary":
                text = _first_text(
                    _summary_text(block.get("summary")),
                    block.get("reasoning") if provider == "openai" else None,
                    block.get("text"),
                    block.get("content"),
                    block.get("delta"),
                )
            elif block_type == "commentary":
                text = _first_text(block.get("text"), block.get("content"), block.get("delta"))
            else:
                text = ""
            if not text:
                continue
            events.append(AgentStreamEvent(
                "work_trace_delta" if block.get("delta") else "work_trace_item",
                {
                    "delta" if block.get("delta") else "text": text,
                    "traceType": block_type,
                    "source": "provider",
                    "data": {"type": raw_type} if raw_type else {},
                },
            ))
        if events:
            return events

    delta = _token_text_delta(token)
    if not delta:
        return []
    return [AgentStreamEvent("model_delta", {
        "delta": delta,
        "metadata": json_safe(metadata),
    })]


def _events_from_updates_chunk(chunk: Any) -> list[AgentStreamEvent]:
    """把 LangChain updates 转成工具调用和工具结果事件，供前端显示工具进度。"""
    data = chunk.get("data") if isinstance(chunk, dict) else None
    if not isinstance(data, dict):
        return []
    events: list[AgentStreamEvent] = []
    for source, update in data.items():
        if not isinstance(update, dict):
            continue
        messages = update.get("messages")
        if not isinstance(messages, list) or not messages:
            continue
        message = messages[-1]
        if isinstance(message, AIMessage):
            reasoning_event = provider_reasoning_event_from_message(message)
            if reasoning_event is not None:
                events.append(reasoning_event)
            if message.tool_calls:
                events.extend(_tool_call_events(message, source=str(source or "")))
        elif isinstance(message, ToolMessage):
            name = str(message.name or "").strip() or "tool"
            events.append(AgentStreamEvent("work_trace_item", {
                "text": f"Tool completed: {name}",
                "traceType": "tool",
                "source": str(source or "") or "tools",
                "data": {
                    "toolName": name,
                    "toolCallId": str(message.tool_call_id or ""),
                    "complete": True,
                },
            }))
    return events


def _events_from_custom_chunk(chunk: Any) -> list[AgentStreamEvent]:
    """把应用自定义 chunk 转成 work trace 事件，供前端显示运行进度。"""
    data = chunk.get("data") if isinstance(chunk, dict) else None
    if isinstance(data, dict):
        text = _first_text(data.get("delta"), data.get("text"), data.get("message"), data.get("detail"))
        if not text:
            return []
        event = "work_trace_delta" if data.get("delta") else "work_trace_item"
        return [AgentStreamEvent(event, {
            "delta" if event == "work_trace_delta" else "text": text,
            "traceType": str(data.get("traceType") or data.get("type") or "status"),
            "source": str(data.get("source") or "langchain"),
            "data": json_safe(data),
        })]
    text = _first_text(data)
    if not text:
        return []
    return [AgentStreamEvent("work_trace_item", {
        "text": text,
        "traceType": "status",
        "source": "langchain",
    })]


# 模型和 provider trace
def _token_text_delta(token: Any) -> str:
    """从模型 token 中提取普通文本增量，跳过工具调用 token，供前端追加模型输出。"""
    if getattr(token, "tool_call_chunks", None):
        return ""
    if getattr(token, "tool_calls", None):
        return ""
    content = getattr(token, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)

    content_blocks = getattr(token, "content_blocks", None)
    if not isinstance(content_blocks, list):
        return ""
    parts: list[str] = []
    for block in content_blocks:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)

def _trace_event_from_payload(payload: dict[str, Any]) -> AgentStreamEvent | None:
    """把 paper_notes_trace payload 转成标准 stream 事件，供前端显示 work trace。"""
    is_delta = "delta" in payload
    text = _first_text(payload.get("delta"), payload.get("text"), payload.get("message"), payload.get("detail"))
    if not text:
        return None
    event_data = {
        "delta" if is_delta else "text": text,
        "traceType": str(payload.get("traceType") or payload.get("type") or "summary"),
        "source": str(payload.get("source") or "provider"),
        "data": json_safe(payload.get("data") if isinstance(payload.get("data"), dict) else payload),
    }
    return AgentStreamEvent("work_trace_delta" if is_delta else "work_trace_item", event_data)


def provider_reasoning_event_from_message(message: AIMessage) -> AgentStreamEvent | None:
    """从完整 AIMessage 中提取 provider reasoning 或 summary 事件，供前端显示可见思考过程。"""
    provider = _message_provider(message)
    parts: list[str] = []
    content_blocks = getattr(message, "content_blocks", None)
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if not isinstance(block, dict) or block.get("type") != "reasoning":
                continue
            summary = block.get("summary")
            if isinstance(summary, str):
                parts.append(summary)
            elif isinstance(summary, list):
                for item in summary:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        text = item.get("text") or item.get("content") or item.get("summary")
                        if isinstance(text, str):
                            parts.append(text)
            if provider == "openai":
                text = block.get("reasoning")
                if isinstance(text, str):
                    parts.append(text)
    summary = "".join(parts).strip()
    if summary:
        return AgentStreamEvent("work_trace_item", {
            "text": summary,
            "traceType": "summary",
            "source": provider,
            "data": {"type": "reasoning_summary"},
        })

    reasoning = _first_text(getattr(message, "additional_kwargs", {}).get("reasoning_content"))
    if not reasoning:
        return None
    return AgentStreamEvent("work_trace_item", {
        "text": reasoning,
        "traceType": "reasoning",
        "source": provider,
        "data": {"type": "reasoning"},
    })


def _message_provider(message: AIMessage) -> str:
    """从消息 metadata 中读取 provider 名称，供后端标记 trace 事件来源。"""
    metadata = getattr(message, "response_metadata", None)
    return str(metadata.get("model_provider") or "provider").strip() if isinstance(metadata, dict) else "provider"

# 前端 activeRun 进度
def _active_run_for_request(session: Any | None, current_request_id: str) -> dict[str, Any]:
    """从会话 metadata 中找到当前请求对应的 activeRun，方便前端刷新后恢复运行进度。"""
    if session is None:
        return {}
    metadata = session.metadata.metadata if isinstance(session.metadata.metadata, dict) else {}
    active_run = metadata.get(ACTIVE_RUN_METADATA_KEY)
    if not isinstance(active_run, dict):
        return {}
    if str(active_run.get("requestId") or "").strip() != current_request_id:
        return {}
    return active_run


def _active_run_progress_payload(
    current_request_id: str,
    *,
    status: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """把 run trace 事件转换成 activeRun.progress，让前端显示当前运行进度。"""
    visible_events = [
        {
            "stage": str(event.get("stage") or event.get("type") or "").strip(),
            "detail": str(event.get("message") or "").strip(),
            "at": str(event.get("at") or "").strip(),
        }
        for event in events
        if str(event.get("message") or "").strip()
    ]
    work_items: list[dict[str, Any]] = []
    for event in events:
        message = str(event.get("message") or "").strip()
        if not message:
            continue
        complete = str(event.get("type") or "").strip() != "work_trace_delta"
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        nested = data.get("data") if isinstance(data.get("data"), dict) else {}
        if complete:
            for payload in (nested, data):
                if payload.get("statusComplete") is False or payload.get("complete") is False:
                    complete = False
                    break
                if payload.get("statusComplete") is True or payload.get("complete") is True:
                    complete = True
                    break
        work_items.append({
            "type": str(event.get("stage") or event.get("type") or "status").strip() or "status",
            "text": message,
            "at": str(event.get("at") or "").strip(),
            "source": str(data.get("source") or "runtime"),
            "data": data,
            "complete": complete,
        })
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


def record_stream_event_in_active_run(
    session_store: Any,
    session_id: str,
    request: Any,
    events: list[dict[str, Any]],
    event: AgentStreamEvent,
) -> None:
    """给流式事件补时间戳，并把最新 activeRun.progress 保存下来给前端显示。"""
    event.data = dict(event.data)
    event.data.setdefault("at", _isoformat_utc(now_utc()))
    trace_event = _run_trace_event_from_stream_event(event)
    if not trace_event:
        return
    events.append(trace_event)
    current_request_id = _request_id(request)
    if not current_request_id:
        return
    current = session_store.get_session(session_id)
    active_run = _active_run_for_request(current, current_request_id)
    if not active_run:
        return
    active_run = dict(active_run)
    active_run["status"] = "running"
    active_run["progress"] = _active_run_progress_payload(current_request_id, status="running", events=events)
    session_store.update_session_metadata(session_id, {ACTIVE_RUN_METADATA_KEY: active_run})




# 时间和请求标识
def now_utc() -> datetime:
    """返回当前 UTC 时间，用来给后端 trace 和运行状态打时间戳。"""
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime) -> str:
    """把时间转换成 UTC ISO 字符串，方便前后端传输和保存。"""
    return value.astimezone(timezone.utc).isoformat()


def _request_id(request: Any) -> str:
    """从前端请求带来的 metadata 中取出当前 requestId，供后端关联本次运行。"""
    return str(request.metadata.get("requestId") or "").strip()


# 流式事件转 runTrace
def is_provider_reasoning_trace_event(event: AgentStreamEvent) -> bool:
    """判断流式事件是否来自模型供应商的推理内容，供后端决定是否过滤。"""
    if event.event not in {"work_trace_item", "work_trace_delta"}:
        return False
    trace_type = str(event.data.get("traceType") or "").strip()
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

# 工具 trace
def _tool_call_events(message: AIMessage, *, source: str) -> list[AgentStreamEvent]:
    """把 AIMessage.tool_calls 转成工具调用 trace 事件，供前端显示工具进度。"""
    events: list[AgentStreamEvent] = []
    for tool_call in message.tool_calls:
        name = str(tool_call.get("name") or "tool").strip()
        args = _tool_args_summary(tool_call.get("args"))
        tool_call_id = str(tool_call.get("id") or tool_call.get("tool_call_id") or "").strip()
        text = f"Calling tool: {name}{f' with args {args}' if args else ''}"
        events.append(AgentStreamEvent("work_trace_item", {
            "text": text,
            "traceType": "tool",
            "source": source or "model",
            "data": {
                "toolName": name,
                "toolCallId": tool_call_id,
                "toolCall": json_safe(tool_call),
                "complete": False,
            },
        }))
    return events


def _tool_args_summary(args: Any) -> str:
    """把工具参数压缩成适合显示的短文本，供前端工具进度使用。"""
    if args is None:
        return ""
    if isinstance(args, str):
        text = args.strip()
    else:
        try:
            text = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
        except TypeError:
            text = str(args).strip()
    if not text:
        return ""
    return f"{text[:277]}..." if len(text) > 280 else text

def _run_trace_event_from_stream_event(event: AgentStreamEvent) -> dict[str, Any] | None:
    """把前端可展示的流式事件转换成 runTrace 事件，之后保存到会话历史里。"""
    if event.event not in {"work_trace_item", "work_trace_delta"}:
        return None
    data = dict(event.data)
    message = str(data.get("text") or data.get("delta") or "").strip()
    if not message:
        return None
    return {
        "type": event.event,
        "stage": str(data.get("traceType") or "").strip(),
        "message": message,
        "at": str(data.get("at") or "").strip(),
        "data": json_safe(data),
    }


def _run_trace_has_equivalent_event(events: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    """判断 runTrace 里是否已经有等价事件，避免后端重复保存相同进度。"""
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


# 最终 runTrace
def stream_final_trace_events_and_build_run_trace(
    request: Any,
    *,
    input_messages: list[BaseMessage],
    final_messages: list[BaseMessage],
    run_events: list[dict[str, Any]],
    started_at: datetime,
    finished_at: datetime,
    include_provider_reasoning: bool = True,
) -> Generator[AgentStreamEvent, None, dict[str, Any]]:
    """产出要通过 SSE 发给前端的最终 trace 事件，并返回要保存到会话里的 runTrace。"""
    final_trace_events: list[AgentStreamEvent] = []
    for message in final_messages:
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
            final_trace_events.append(AgentStreamEvent("work_trace_item", {
                "text": text,
                "traceType": str(item.get("traceType") or "summary"),
                "source": str(item.get("source") or "codex"),
                "data": json_safe(item.get("data") if isinstance(item.get("data"), dict) else item),
            }))
        reasoning_event = provider_reasoning_event_from_message(message) if include_provider_reasoning else None
        if reasoning_event is not None:
            final_trace_events.append(reasoning_event)

    seen_final_events: set[tuple[str, str, str]] = set()
    for event in final_trace_events:
        key = (
            str(event.data.get("traceType") or ""),
            str(event.data.get("source") or ""),
            str(event.data.get("text") or event.data.get("delta") or ""),
        )
        if key in seen_final_events:
            continue
        seen_final_events.add(key)
        event.data.setdefault("at", _isoformat_utc(finished_at))
        trace_event = _run_trace_event_from_stream_event(event)
        if trace_event and _run_trace_has_equivalent_event(run_events, trace_event):
            continue
        if trace_event:
            run_events.append(trace_event)
        yield event

    if len(final_messages) > len(input_messages):
        new_messages = final_messages[len(input_messages):]
    else:
        new_messages = final_messages[-1:] if final_messages else []
    for trace_event in build_model_response_trace_events(new_messages, at=finished_at):
        if _run_trace_has_equivalent_event(run_events, trace_event):
            continue
        run_events.append(trace_event)

    duration_ms = max(0, round((finished_at - started_at).total_seconds() * 1000))
    current_request_id = _request_id(request)
    return {
        "requestId": current_request_id,
        "startedAt": _isoformat_utc(started_at),
        "finishedAt": _isoformat_utc(finished_at),
        "durationMs": duration_ms,
        "status": "completed",
        "events": list(run_events),
    }


def build_model_response_trace_events(messages: list[BaseMessage], *, at: datetime) -> list[dict[str, Any]]:
    """从最终模型消息中提取 web search 概览事件，放进前端可查看的 runTrace。"""
    events: list[dict[str, Any]] = []
    for turn, message in enumerate(messages, start=1):
        if not isinstance(message, AIMessage):
            continue

        calls: list[Any] = []
        sources: list[dict[str, str]] = []
        queries: list[str] = []
        seen_urls: set[str] = set()
        content = getattr(message, "content", None)
        content_blocks = content if isinstance(content, list) else []
        for block in content_blocks:
            _collect_web_search_trace_from_block(block, calls=calls, sources=sources, queries=queries, seen_urls=seen_urls)
        additional_kwargs = getattr(message, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict):
            for item in additional_kwargs.get("tool_outputs") or []:
                _collect_web_search_trace_from_block(item, calls=calls, sources=sources, queries=queries, seen_urls=seen_urls)
        if not calls:
            continue

        source_count = len(sources)
        source_text = (
            f" and {source_count} source{'s' if source_count != 1 else ''}"
            if source_count
            else ""
        )
        metadata = getattr(message, "response_metadata", None)
        source = "provider"
        if isinstance(metadata, dict):
            source = str(metadata.get("model_provider") or "").strip() or source
        events.append({
            "type": "model_response",
            "stage": "model_response",
            "message": (
                "Model provider returned a response with "
                f"{len(calls)} web search call{'s' if len(calls) != 1 else ''}"
                f"{source_text}."
            ),
            "at": _isoformat_utc(at),
            "data": {
                "turn": turn,
                "source": source,
                "webSearchCallCount": len(calls),
                **({"webSearchSourceCount": source_count} if sources else {}),
                **({"webSearchQueries": queries[:6]} if queries else {}),
            },
        })
    return events


# Web search trace 提取
def _collect_web_search_trace_from_block(
    block: Any,
    *,
    calls: list[Any],
    sources: list[dict[str, str]],
    queries: list[str],
    seen_urls: set[str],
) -> None:
    """从模型响应 block 中收集 web search 调用、来源和查询词，供后端生成 runTrace。"""
    if not isinstance(block, dict):
        return
    block_type = str(block.get("type") or "").strip()
    name = str(block.get("name") or "").strip()
    if block_type == "web_search_call" or (block_type == "server_tool_use" and name == "web_search"):
        calls.append(block)
        _collect_web_search_queries(block, queries, set(queries), depth=0)
        _collect_sources_from_value(block, sources=sources, seen_urls=seen_urls)
    if block_type == "web_search_tool_result":
        _collect_sources_from_value(block, sources=sources, seen_urls=seen_urls)
    for annotation in block.get("annotations") or []:
        _collect_source_from_mapping(annotation, sources=sources, seen_urls=seen_urls)

def _collect_sources_from_value(value: Any, *, sources: list[dict[str, str]], seen_urls: set[str], depth: int = 0) -> None:
    """递归扫描任意值里的引用来源 URL，供后端整理 web search 来源。"""
    if depth > 5:
        return
    if isinstance(value, dict):
        _collect_source_from_mapping(value, sources=sources, seen_urls=seen_urls)
        for item in value.values():
            _collect_sources_from_value(item, sources=sources, seen_urls=seen_urls, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _collect_sources_from_value(item, sources=sources, seen_urls=seen_urls, depth=depth + 1)

def _collect_source_from_mapping(value: dict[str, Any], *, sources: list[dict[str, str]], seen_urls: set[str]) -> None:
    """从一个 mapping 中提取单条来源信息，供后端整理 web search 来源列表。"""
    url = str(value.get("url") or value.get("uri") or "").strip()
    if not url or url in seen_urls:
        return
    seen_urls.add(url)
    sources.append({
        "title": str(value.get("title") or "").strip(),
        "url": url,
        "snippet": str(value.get("snippet") or value.get("text") or "").strip(),
    })

def _collect_web_search_queries(value: Any, queries: list[str], seen: set[str], *, depth: int) -> None:
    """递归提取 web search 查询词，并限制数量和深度，供后端生成 runTrace 摘要。"""
    if depth > 4 or len(queries) >= 6:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip()
            if normalized_key in {"query", "queries", "search_query", "searchQuery", "webSearchQueries", "web_search_queries"}:
                _append_web_search_query(item, queries, seen)
                if len(queries) >= 6:
                    return
                continue
            _collect_web_search_queries(item, queries, seen, depth=depth + 1)
            if len(queries) >= 6:
                return
        return
    if isinstance(value, list):
        for item in value:
            _collect_web_search_queries(item, queries, seen, depth=depth + 1)
            if len(queries) >= 6:
                return

def _append_web_search_query(value: Any, queries: list[str], seen: set[str]) -> None:
    """把查询词加入列表，并负责去重和截断，供后端展示简短搜索摘要。"""
    if isinstance(value, list):
        for item in value:
            _append_web_search_query(item, queries, seen)
            if len(queries) >= 6:
                return
        return
    if isinstance(value, dict):
        _collect_web_search_queries(value, queries, seen, depth=0)
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


# 会话持久化
def attach_run_trace_to_latest_assistant(messages: list[dict[str, Any]], run_trace: dict[str, Any] | None) -> list[dict[str, Any]]:
    """把 runTrace 挂到最后一条 assistant transcript 消息上，方便之后打开会话时查看。"""
    if not run_trace:
        return messages
    updated = [dict(message) for message in messages]
    for index in range(len(updated) - 1, -1, -1):
        if updated[index].get("role") == "assistant":
            updated[index]["runTrace"] = copy.deepcopy(run_trace)
            break
    return updated


def save_active_run_metadata(
    session_store: Any,
    session: Any,
    request: Any,
    *,
    input_messages: list[BaseMessage],
    provider: str,
    model: str,
) -> Any:
    """保存当前用户请求 transcript，并写入 activeRun metadata，方便前端刷新后恢复状态。"""
    transcript = messages_to_transcript(input_messages)
    transcript = merge_existing_transcript_fields(transcript, session.messages)
    persisted = session_store.replace_messages(session.metadata.session_id, transcript)
    current_request_id = _request_id(request)
    if current_request_id:
        metadata = {
            "requestId": current_request_id,
            "status": "running",
            "startedAt": _isoformat_utc(now_utc()),
            "provider": provider,
            "model": model,
            "noteId": request.note_id or "",
            "message": content_text(request_message_content(request)).strip()[:500],
            "progress": _active_run_progress_payload(current_request_id, status="running", events=[]),
        }
        session_store.update_session_metadata(session.metadata.session_id, {ACTIVE_RUN_METADATA_KEY: metadata})
        persisted = session_store.require_session(session.metadata.session_id)
    return persisted


def finish_active_run_metadata(
    session_store: Any,
    session_id: str,
    request: Any,
    *,
    status: str,
    error_text: str = "",
) -> None:
    """按完成或失败状态更新会话 metadata，关闭当前 activeRun。"""
    current_request_id = _request_id(request)
    if not current_request_id:
        return
    current = session_store.get_session(session_id)
    active_run = _active_run_for_request(current, current_request_id)
    if not active_run:
        return
    metadata = dict(current.metadata.metadata)
    if status == "completed":
        metadata.pop(ACTIVE_RUN_METADATA_KEY, None)
    else:
        failed = dict(active_run)
        failed["status"] = status
        failed["finishedAt"] = _isoformat_utc(now_utc())
        if error_text:
            failed["error"] = error_text
        metadata[ACTIVE_RUN_METADATA_KEY] = failed
    session_store.update_session_metadata(session_id, metadata, replace=True)


# 通用文本处理
def _first_text(*values: Any) -> str:
    """返回传入值中的第一段非空字符串，供后端解析各种 provider payload。"""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def _summary_text(summary: Any) -> str:
    """把 provider 返回的 summary 字段规整成一段可展示文本，供 trace 事件使用。"""
    if isinstance(summary, str):
        return summary.strip()
    if not isinstance(summary, list):
        return ""
    parts: list[str] = []
    for item in summary:
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
        elif isinstance(item, dict):
            text = _first_text(item.get("text"), item.get("content"), item.get("summary"))
            if text:
                parts.append(text)
    return "".join(parts).strip()
