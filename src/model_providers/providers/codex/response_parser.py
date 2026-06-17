"""说明：解析 Codex 非流式 response。

作用：把 Codex Responses API 的输出转换成 Paper Notes 内部统一的 assistant 消息和工具结果。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage

from model_providers.providers.codex.response_common import (
    CODEX_PROVIDER_NAME,
    first_int as _first_int,
    get_attr as _get_attr,
    image_generation_options as _image_generation_options,
    json_safe as _json_safe,
    normalize_phase as _normalize_phase,
)

__all__ = [
    "message_from_responses_response",
    "provider_trace",
    "response_message_text",
]

def _message_from_responses_response(response: Any, *, options: dict[str, Any], model: str) -> AIMessage:
    content, tool_calls, info = _parse_responses_response(response, options=options, model=model)
    if not content and not tool_calls and not info.get("artifacts"):
        info["empty_response"] = True
    return AIMessage(
        content="" if tool_calls else content,
        tool_calls=tool_calls,
        response_metadata=info,
    )


def _parse_responses_response(response: Any, *, options: dict[str, Any], model: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    content_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    work_trace: list[dict[str, Any]] = []
    model_trace: list[dict[str, Any]] = []
    for item in _response_output_items(response):
        item_type = str(_get_attr(item, "type", "") or "")
        if item_type == "message":
            text = _response_message_text(item)
            phase = _normalize_phase(_get_attr(item, "phase", ""))
            if text and phase in {"commentary", "analysis"}:
                model_trace.append(_provider_trace(text, trace_type="commentary", item=item))
            elif text:
                content_parts.append(text)
            continue
        if item_type == "reasoning":
            for text in _reasoning_summary_texts(item):
                model_trace.append(_provider_trace(text, trace_type="summary", item=item))
            continue
        if item_type in {"function_call", "custom_tool_call"}:
            call = _tool_call_from_response_item(item, index=len(tool_calls), custom=item_type == "custom_tool_call")
            if call:
                tool_calls.append(call)
            continue
        if item_type == "image_generation_call":
            if _get_attr(item, "result", None):
                work_trace.append(_provider_trace("Codex generated image.", trace_type="tool", item=item))
            continue
        if item_type == "web_search_call":
            query = _web_search_query(item)
            if query:
                work_trace.append(_provider_trace(f"Codex searched web: {query}", trace_type="tool", item=item))
    content = "\n".join(part for part in content_parts if part).strip()
    if not content:
        content = str(_get_attr(response, "output_text", "") or "").strip()
    info = {
        "model_provider": CODEX_PROVIDER_NAME,
        "response_id": _get_attr(response, "id", None),
        "status": str(_get_attr(response, "status", "") or ""),
        "codex_work_trace": work_trace,
        "codex_model_trace": _dedupe_traces(model_trace),
    }
    usage = _usage_from_response(response)
    if usage:
        info["usage"] = usage
    artifacts = _image_artifacts_from_response(response, options=options, model=model)
    if artifacts:
        info["artifacts"] = artifacts
    return content, tool_calls, {key: value for key, value in info.items() if value not in (None, "", [])}


def _tool_call_from_response_item(item: Any, *, index: int, custom: bool = False) -> dict[str, Any] | None:
    name = str(_get_attr(item, "name", "") or "").strip()
    if not name:
        return None
    raw_args = _get_attr(item, "input", "{}") if custom else _get_attr(item, "arguments", "{}")
    args = _json_args(raw_args)
    call_id = str(_get_attr(item, "call_id", "") or _get_attr(item, "id", "") or f"call_{uuid.uuid4().hex[:12]}_{index}")
    return {"name": name, "args": args, "id": call_id}


def _json_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError:
            return {"input": value}
        return parsed if isinstance(parsed, dict) else {"input": parsed}
    return {"input": value} if value is not None else {}


def _response_output_items(response: Any) -> list[Any]:
    output = _get_attr(response, "output", None)
    return output if isinstance(output, list) else []


def _response_message_text(item: Any) -> str:
    content = _get_attr(item, "content", None)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        part_type = str(_get_attr(part, "type", "") or "")
        if part_type not in {"output_text", "text"}:
            continue
        text = _get_attr(part, "text", "")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts).strip()


def _reasoning_summary_texts(item: Any) -> list[str]:
    summary = _get_attr(item, "summary", None)
    if isinstance(summary, str):
        return [summary] if summary.strip() else []
    if not isinstance(summary, list):
        return []
    texts: list[str] = []
    for part in summary:
        text = part if isinstance(part, str) else _get_attr(part, "text", _get_attr(part, "content", ""))
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    return texts


def _web_search_query(item: Any) -> str:
    action = _get_attr(item, "action", None)
    for key in ("query", "queries"):
        value = _get_attr(action, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value:
            return ", ".join(str(part) for part in value[:3] if str(part).strip())
    return ""


def _image_artifacts_from_response(response: Any, *, options: dict[str, Any], model: str) -> list[dict[str, Any]]:
    config = _image_generation_options(options)
    media_store = options.get("_write_note_media_store")
    create_generated_image = getattr(media_store, "create_generated_image", None)
    if not callable(create_generated_image):
        return []
    session_id = str(options.get("_paper_notes_session_id") or "")
    provider = str(options.get("_paper_notes_provider") or CODEX_PROVIDER_NAME)
    artifacts: list[dict[str, Any]] = []
    for item in _response_output_items(response):
        if str(_get_attr(item, "type", "") or "") != "image_generation_call":
            continue
        result = _get_attr(item, "result", None)
        if not isinstance(result, str) or not result:
            continue
        artifact = create_generated_image(
            result,
            session_id=session_id,
            provider=provider,
            model=model,
            file_format=str(config.get("format") or config.get("output_format") or "png"),
            metadata={
                "response_id": _get_attr(response, "id", None),
                "generation_call_id": _get_attr(item, "id", None),
                "revised_prompt": _get_attr(item, "revised_prompt", None),
                "size": config.get("size"),
                "quality": config.get("quality"),
            },
        )
        to_dict = getattr(artifact, "to_dict", None)
        artifacts.append(to_dict() if callable(to_dict) else dict(artifact))
    return artifacts


def _provider_trace(text: str, *, trace_type: str, item: Any, delta: bool = False) -> dict[str, Any]:
    payload_key = "delta" if delta else "text"
    return {
        payload_key: text,
        "text": text,
        "traceType": trace_type,
        "source": "codex",
        "data": _trace_item_data(item),
    }


def _trace_item_data(item: Any) -> Any:
    data = _json_safe(item)
    if str(_get_attr(item, "type", "") or "") == "image_generation_call" and not isinstance(data, dict):
        data = {
            "type": "image_generation_call",
            "id": _get_attr(item, "id", None),
            "status": _get_attr(item, "status", None),
            "result": _get_attr(item, "result", None),
        }
    if isinstance(data, dict) and data.get("type") == "image_generation_call":
        data = dict(data)
        if data.get("result"):
            data["result"] = "[image data omitted]"
    return data


def _dedupe_traces(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (str(item.get("traceType") or ""), str(item.get("text") or item.get("delta") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _usage_from_response(response: Any) -> dict[str, int]:
    usage = _get_attr(response, "usage", None)
    if usage is None:
        return {}
    input_tokens = _first_int(usage, "input_tokens", "prompt_tokens", "inputTokens", "promptTokens")
    output_tokens = _first_int(usage, "output_tokens", "completion_tokens", "outputTokens", "completionTokens")
    total_tokens = _first_int(usage, "total_tokens", "totalTokens") or input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }

message_from_responses_response = _message_from_responses_response
provider_trace = _provider_trace
response_message_text = _response_message_text
tool_call_from_response_item = _tool_call_from_response_item
