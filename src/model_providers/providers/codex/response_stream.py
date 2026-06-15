from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from model_providers.providers.codex.response_common import (
    get_attr as _get_attr,
    normalize_phase as _normalize_phase,
    set_attr as _set_attr,
)
from model_providers.providers.codex.response_parser import (
    message_from_responses_response as _message_from_responses_response,
    provider_trace as _provider_trace,
    response_message_text as _response_message_text,
)


def _stream_chunk_from_responses_event(event: Any) -> list[ChatGenerationChunk]:
    event_type = str(_get_attr(event, "type", "") or "")
    if event_type in {"response.output_text.delta", "response.text.delta"}:
        delta = str(_get_attr(event, "delta", "") or "")
        return [_content_generation_chunk(delta)] if delta else []
    if event_type in {"response.reasoning_summary_text.delta", "response.reasoning.delta"}:
        delta = str(_get_attr(event, "delta", "") or "")
        return [_trace_generation_chunk(_provider_trace(delta, trace_type="summary", item=event, delta=True))] if delta else []
    if event_type in {"response.output_item.done", "response.output_item.completed"}:
        item = _get_attr(event, "item", None)
        if str(_get_attr(item, "type", "") or "") != "message":
            return []
        phase = _normalize_phase(_get_attr(item, "phase", ""))
        if phase not in {"commentary", "analysis"}:
            return []
        text = _response_message_text(item)
        return [_trace_generation_chunk(_provider_trace(text, trace_type="commentary", item=item))] if text else []
    return []


def _content_generation_chunk(delta: str) -> ChatGenerationChunk:
    return ChatGenerationChunk(message=AIMessageChunk(content=delta))


def _trace_generation_chunk(trace: dict[str, Any]) -> ChatGenerationChunk:
    return ChatGenerationChunk(
        message=AIMessageChunk(content="", response_metadata={"paper_notes_trace": [trace]}),
    )


def _final_generation_chunk_from_response(
    response: Any,
    *,
    suppress_content: bool,
    options: dict[str, Any],
    model: str,
) -> ChatGenerationChunk:
    message = _message_from_responses_response(response, options=options, model=model)
    tool_call_chunks = _tool_call_chunks_from_tool_calls(message.tool_calls)
    return ChatGenerationChunk(
        message=AIMessageChunk(
            content="" if tool_call_chunks or suppress_content else str(message.content or ""),
            tool_call_chunks=tool_call_chunks,
            chunk_position="last",
            response_metadata=dict(message.response_metadata or {}),
        ),
        generation_info=dict(message.response_metadata or {}),
    )


def _backfill_stream_output(
    response: Any | None,
    *,
    collected_output_items: list[Any],
    collected_text_deltas: list[str],
) -> Any | None:
    if response is None:
        if not collected_output_items and not collected_text_deltas:
            return None
        response = SimpleNamespace(id="", status="completed", output=[], output_text="", usage=None)
    output = _get_attr(response, "output", None)
    if isinstance(output, list) and output:
        return response
    if collected_output_items:
        _set_attr(response, "output", list(collected_output_items))
        return response
    if collected_text_deltas:
        text = "".join(collected_text_deltas)
        _set_attr(response, "output", [
            SimpleNamespace(
                type="message",
                role="assistant",
                status="completed",
                content=[SimpleNamespace(type="output_text", text=text)],
            )
        ])
        if not _get_attr(response, "output_text", ""):
            _set_attr(response, "output_text", text)
    return response


def _tool_call_chunks_from_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        chunks.append({
            "name": str(tool_call.get("name") or ""),
            "args": json.dumps(tool_call.get("args") or {}, ensure_ascii=False, separators=(",", ":")),
            "id": str(tool_call.get("id") or f"call_{uuid.uuid4().hex[:12]}_{index}"),
            "index": index,
        })
    return chunks


backfill_stream_output = _backfill_stream_output
final_generation_chunk_from_response = _final_generation_chunk_from_response
stream_chunk_from_responses_event = _stream_chunk_from_responses_event
tool_call_chunks_from_tool_calls = _tool_call_chunks_from_tool_calls


__all__ = [
    "backfill_stream_output",
    "final_generation_chunk_from_response",
    "stream_chunk_from_responses_event",
    "tool_call_chunks_from_tool_calls",
]
