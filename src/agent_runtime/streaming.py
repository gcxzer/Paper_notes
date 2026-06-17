from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


LANGCHAIN_AGENT_STREAM_MODES = ["messages", "updates", "values", "custom"]
PROVIDER_TRACE_BLOCK_TYPES = {
    "commentary": "commentary",
    "summary": "summary",
}
RAW_PROVIDER_REASONING_BLOCK_TYPES = {"reasoning", "thinking", "thought"}


@dataclass(slots=True)
class AgentStreamEvent:
    event: str
    data: dict[str, Any]


def events_from_langchain_chunk(chunk: Any) -> list[AgentStreamEvent]:
    mode = _chunk_type(chunk)
    if mode == "messages":
        return _events_from_messages_chunk(chunk)
    if mode == "updates":
        return _events_from_updates_chunk(chunk)
    if mode == "custom":
        return _events_from_custom_chunk(chunk)
    return []


def _chunk_type(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return str(chunk.get("type") or "").strip()
    return ""


def _chunk_data(chunk: Any) -> Any:
    return chunk.get("data") if isinstance(chunk, dict) else None


def _events_from_messages_chunk(chunk: Any) -> list[AgentStreamEvent]:
    data = _chunk_data(chunk)
    if not isinstance(data, tuple | list) or len(data) < 2:
        return []
    token, metadata = data[0], data[1]
    if not _is_main_model_stream(metadata):
        return []
    trace_events = _token_trace_events(token)
    if trace_events:
        return trace_events
    delta = _token_text_delta(token)
    if not delta:
        return []
    return [AgentStreamEvent("model_delta", {
        "delta": delta,
        "metadata": _json_safe(metadata),
    })]


def _events_from_updates_chunk(chunk: Any) -> list[AgentStreamEvent]:
    data = _chunk_data(chunk)
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
            events.append(_tool_result_event(message, source=str(source or "")))
    return events


def _events_from_custom_chunk(chunk: Any) -> list[AgentStreamEvent]:
    data = _chunk_data(chunk)
    if isinstance(data, dict):
        text = _first_text(data.get("delta"), data.get("text"), data.get("message"), data.get("detail"))
        if not text:
            return []
        event = "work_trace_delta" if data.get("delta") else "work_trace_item"
        return [AgentStreamEvent(event, {
            "delta" if event == "work_trace_delta" else "text": text,
            "traceType": str(data.get("traceType") or data.get("type") or "status"),
            "source": str(data.get("source") or "langchain"),
            "data": _json_safe(data),
        })]
    text = _first_text(data)
    if not text:
        return []
    return [AgentStreamEvent("work_trace_item", {
        "text": text,
        "traceType": "status",
        "source": "langchain",
    })]


def _is_main_model_stream(metadata: Any) -> bool:
    if not isinstance(metadata, dict):
        return True
    node = str(metadata.get("langgraph_node") or "").strip()
    return not node or node == "model"


def _token_text_delta(token: Any) -> str:
    if getattr(token, "tool_call_chunks", None):
        return ""
    if getattr(token, "tool_calls", None):
        return ""
    text = _content_text(getattr(token, "content", ""))
    if text:
        return text
    return _content_blocks_text(getattr(token, "content_blocks", None))


def _token_trace_events(token: Any) -> list[AgentStreamEvent]:
    events = _paper_notes_trace_events(token)
    if events:
        return events
    return _content_block_trace_events(
        getattr(token, "content_blocks", None),
        provider=_message_provider(token),
    )


def _paper_notes_trace_events(token: Any) -> list[AgentStreamEvent]:
    metadata = getattr(token, "response_metadata", None)
    trace = metadata.get("paper_notes_trace") if isinstance(metadata, dict) else None
    if isinstance(trace, dict):
        event = _trace_event_from_payload(trace)
        return [event] if event else []
    if isinstance(trace, list):
        return [event for item in trace if isinstance(item, dict) if (event := _trace_event_from_payload(item))]
    return []


def _content_block_trace_events(content_blocks: Any, *, provider: str = "") -> list[AgentStreamEvent]:
    if not isinstance(content_blocks, list):
        return []
    events: list[AgentStreamEvent] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "non_standard" and isinstance(block.get("value"), dict):
            block = block["value"]
        block_type = _provider_trace_block_type(block, provider=provider)
        if not block_type:
            continue
        text = _provider_trace_text(block, block_type, provider=provider)
        if not text:
            continue
        events.append(AgentStreamEvent(
            "work_trace_delta" if block.get("delta") else "work_trace_item",
            {
                "delta" if block.get("delta") else "text": text,
                "traceType": block_type,
                "source": "provider",
                "data": _provider_trace_data(block),
            },
        ))
    return events


def _provider_trace_block_type(block: dict[str, Any], *, provider: str = "") -> str:
    raw_type = str(block.get("type") or "").strip()
    block_type = PROVIDER_TRACE_BLOCK_TYPES.get(raw_type)
    if block_type:
        return block_type
    if raw_type in RAW_PROVIDER_REASONING_BLOCK_TYPES and _summary_text(block.get("summary")):
        return "summary"
    if raw_type == "reasoning" and provider == "openai" and _first_text(block.get("reasoning")):
        return "summary"
    return ""


def _provider_trace_text(block: dict[str, Any], block_type: str, *, provider: str = "") -> str:
    if block_type == "summary":
        return _first_text(
            _summary_text(block.get("summary")),
            block.get("reasoning") if provider == "openai" else None,
            block.get("text"),
            block.get("content"),
            block.get("delta"),
        )
    if block_type == "commentary":
        return _first_text(block.get("text"), block.get("content"), block.get("delta"))
    return ""


def _summary_text(summary: Any) -> str:
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


def _provider_trace_data(block: dict[str, Any]) -> dict[str, str]:
    raw_type = str(block.get("type") or "").strip()
    return {"type": raw_type} if raw_type else {}


def _trace_event_from_payload(payload: dict[str, Any]) -> AgentStreamEvent | None:
    is_delta = "delta" in payload
    text = _first_text(payload.get("delta"), payload.get("text"), payload.get("message"), payload.get("detail"))
    if not text:
        return None
    event_data = {
        "delta" if is_delta else "text": text,
        "traceType": str(payload.get("traceType") or payload.get("type") or "summary"),
        "source": str(payload.get("source") or "provider"),
        "data": _json_safe(payload.get("data") if isinstance(payload.get("data"), dict) else payload),
    }
    return AgentStreamEvent("work_trace_delta" if is_delta else "work_trace_item", event_data)


def _content_text(content: Any) -> str:
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
    return ""


def _content_blocks_text(content_blocks: Any) -> str:
    if not isinstance(content_blocks, list):
        return ""
    parts: list[str] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _tool_call_events(message: AIMessage, *, source: str) -> list[AgentStreamEvent]:
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
                "toolCall": _json_safe(tool_call),
                "complete": False,
            },
        }))
    return events


def _tool_result_event(message: ToolMessage, *, source: str) -> AgentStreamEvent:
    name = str(message.name or "").strip() or "tool"
    return AgentStreamEvent("work_trace_item", {
        "text": f"Tool completed: {name}",
        "traceType": "tool",
        "source": source or "tools",
        "data": {
            "toolName": name,
            "toolCallId": str(message.tool_call_id or ""),
            "complete": True,
        },
    })


def provider_reasoning_event_from_message(message: AIMessage) -> AgentStreamEvent | None:
    provider = _message_provider(message)
    summary = _reasoning_summary_from_content_blocks(getattr(message, "content_blocks", None), provider=provider)
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


def _reasoning_summary_from_content_blocks(content_blocks: Any, *, provider: str = "") -> str:
    if not isinstance(content_blocks, list):
        return ""
    parts: list[str] = []
    for block in content_blocks:
        if not isinstance(block, dict) or block.get("type") != "reasoning":
            continue
        parts.extend(_summary_text_parts(block.get("summary")))
        if provider == "openai":
            text = block.get("reasoning")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _summary_text_parts(summary: Any) -> list[str]:
    if isinstance(summary, str):
        return [summary]
    if not isinstance(summary, list):
        return []
    parts: list[str] = []
    for item in summary:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("content") or item.get("summary")
            if isinstance(text, str):
                parts.append(text)
    return parts


def _message_provider(message: AIMessage) -> str:
    metadata = getattr(message, "response_metadata", None)
    return str(metadata.get("model_provider") or "provider").strip() if isinstance(metadata, dict) else "provider"


def _tool_args_summary(args: Any) -> str:
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


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, BaseMessage):
        return _json_safe({
            "type": value.type,
            "content": value.content,
            "name": value.name,
        })
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(mode="json"))
        except TypeError:
            return _json_safe(model_dump())
    return str(value)
