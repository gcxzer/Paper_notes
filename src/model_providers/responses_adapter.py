"""Responses API request/response adapter.

Adapted from Nous Research Hermes Agent's ``agent/codex_responses_adapter.py``.
Hermes Agent is MIT licensed, Copyright (c) 2025 Nous Research.

This module is intentionally pure adapter code: it converts Paper Notes'
internal chat-style messages into OpenAI Responses API input items, validates
Codex-compatible payloads, and normalizes Responses output back into the local
``ModelResponse`` shape.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from model_providers.errors import ModelProviderConfigError
from model_providers.image_routing import (
    decide_image_input_route,
    image_generation_unsupported_message,
    image_input_unsupported_message,
    supports_image_generation,
)
from model_providers.types import ModelRequest, ModelResponse, TokenUsage, ToolCall


logger = logging.getLogger(__name__)

CODEX_PROVIDER_NAME = "codex-oauth"
_RESPONSE_MESSAGE_STATUSES = {"completed", "incomplete", "in_progress"}
_INCOMPLETE_STATUSES = {"queued", "in_progress", "incomplete"}
_TOOL_CALL_LEAK_PATTERN = re.compile(r"(?:^|[\s>|])to=functions\.[A-Za-z_][\w.]*", re.IGNORECASE)


def build_responses_payload(
    request: ModelRequest,
    *,
    model: str,
    provider_name: str,
    codex_strict: bool = False,
) -> dict[str, Any]:
    message_instructions, input_items = split_instructions_and_input(
        request.messages,
        request.request_options,
        provider_name=provider_name,
        model=model,
    )
    payload: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "store": False,
    }
    resolved_instructions = combine_instructions(request.instructions, message_instructions)
    if resolved_instructions or codex_strict:
        payload["instructions"] = resolved_instructions or ""

    raw_tools = list(request.tools)
    if _provider_native_web_search_enabled(request.request_options):
        raw_tools.append({"type": "web_search"})
    tools = to_responses_tools(raw_tools)
    if tools:
        if has_image_generation_tool(tools) and not supports_image_generation(provider_name, model):
            raise ModelProviderConfigError(image_generation_unsupported_message(provider_name, model))
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
        if has_web_search_tool(tools):
            payload["include"] = _merge_include(
                payload.get("include"),
                ["web_search_call.action.sources"],
            )

    if request.max_output_tokens is not None:
        payload["max_output_tokens"] = request.max_output_tokens

    payload.update({key: value for key, value in request.request_options.items() if not str(key).startswith("_")})
    if tools and has_web_search_tool(tools):
        payload["include"] = _merge_include(
            payload.get("include"),
            ["web_search_call.action.sources"],
        )
    if _work_trace_enabled(request.request_options, provider_name=provider_name) and not _reasoning_effort_is_none(payload):
        reasoning = payload.get("reasoning") if isinstance(payload.get("reasoning"), dict) else {}
        payload["reasoning"] = {**reasoning, "summary": reasoning.get("summary") or "auto"}
        payload["include"] = _merge_include(payload.get("include"), ["reasoning.encrypted_content"])
    if codex_strict:
        return preflight_codex_payload(payload)
    return payload


def combine_instructions(*parts: str | None) -> str | None:
    instructions = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    return "\n\n".join(instructions) if instructions else None


def split_instructions_and_input(
    messages: list[dict[str, Any]],
    request_options: dict[str, Any] | None = None,
    *,
    provider_name: str = "openai",
    model: str = "",
) -> tuple[str | None, list[dict[str, Any]]]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    media_store = (request_options or {}).get("_paper_notes_media_store")
    image_route = decide_image_input_route(provider_name, model)
    seen_replay_item_ids: set[str] = set()

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        content = message.get("content", "")
        if role in {"system", "developer"}:
            text = stringify_content(content)
            if text:
                instructions.append(text)
            continue
        if role == "tool":
            call_id, _ = split_responses_tool_id(message.get("tool_call_id") or message.get("call_id"))
            if call_id:
                input_items.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": stringify_content(content),
                })
            continue
        if role == "assistant":
            _append_assistant_replay_items(input_items, message, seen_replay_item_ids)
            if not _has_replayed_message_items(message):
                parts = responses_content_parts(
                    role,
                    content,
                    message.get("attachments"),
                    media_store=media_store,
                    image_route=image_route,
                )
                if parts:
                    input_items.append({"role": "assistant", "content": parts})
                elif _has_codex_reasoning_items(message):
                    input_items.append({"role": "assistant", "content": ""})
            input_items.extend(assistant_tool_calls_to_response_items(message.get("tool_calls") or []))
            continue
        if role == "user":
            parts = responses_content_parts(
                role,
                content,
                message.get("attachments"),
                media_store=media_store,
                image_route=image_route,
            )
            input_items.append({"role": "user", "content": parts if parts else ""})

    return "\n\n".join(instructions) or None, input_items


def responses_content_parts(
    role: str,
    content: Any,
    attachments: Any = None,
    *,
    media_store: Any = None,
    image_route: Any = None,
) -> list[dict[str, Any]]:
    text_type = "output_text" if role == "assistant" else "input_text"
    parts: list[dict[str, Any]] = []
    if isinstance(content, list):
        for item in content:
            part = responses_content_part(item, text_type=text_type, image_route=image_route)
            if part is not None:
                parts.append(part)
    else:
        text = stringify_content(content)
        if text:
            parts.append({"type": text_type, "text": text})

    for attachment in attachment_items(attachments):
        if attachment_is_image(attachment):
            if image_route is not None and not image_route.native:
                raise ModelProviderConfigError(image_input_unsupported_message(image_route))
            data_url = attachment_data_url(attachment, media_store)
            if data_url:
                parts.append({"type": "input_image", "image_url": data_url})
            continue
        text = attachment_text(attachment, media_store)
        if text:
            parts.append({"type": text_type, "text": text})
    return parts


def responses_content_part(
    part: Any,
    *,
    text_type: str,
    image_route: Any = None,
) -> dict[str, Any] | None:
    if isinstance(part, str):
        return {"type": text_type, "text": part} if part else None
    if not isinstance(part, dict):
        text = stringify_content(part)
        return {"type": text_type, "text": text} if text else None

    part_type = str(part.get("type") or "").strip().lower()
    if part_type in {"text", "input_text", "output_text"}:
        text = stringify_content(part.get("text", part.get("content", "")))
        return {"type": text_type, "text": text} if text else None
    if part_type in {"image_url", "input_image"}:
        if image_route is not None and not image_route.native:
            raise ModelProviderConfigError(image_input_unsupported_message(image_route))
        if part.get("file_id"):
            return {"type": "input_image", "file_id": part.get("file_id")}
        image_url = part.get("image_url")
        detail = part.get("detail")
        if isinstance(image_url, dict):
            detail = image_url.get("detail", detail)
            image_url = image_url.get("url")
        if not image_url:
            return None
        image_part: dict[str, Any] = {"type": "input_image", "image_url": str(image_url)}
        if isinstance(detail, str) and detail.strip():
            image_part["detail"] = detail.strip()
        return image_part
    return dict(part)


def to_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and "function" in tool:
            function = tool.get("function") or {}
            name = function.get("name")
            if not name:
                continue
            next_tool = {
                "type": "function",
                "name": str(name),
                "description": stringify_content(function.get("description", "")),
                "parameters": function.get("parameters", {"type": "object", "properties": {}}),
            }
            if "strict" in function:
                next_tool["strict"] = bool(function["strict"])
            converted.append(next_tool)
            continue
        if tool.get("type") == "function" and tool.get("name"):
            next_tool = dict(tool)
            next_tool.setdefault("parameters", {"type": "object", "properties": {}})
            converted.append(next_tool)
            continue
        tool_type = str(tool.get("type") or "")
        if tool_type and tool_type != "function":
            converted.append(dict(tool))
    return converted


def has_image_generation_tool(tools: list[dict[str, Any]]) -> bool:
    return any(isinstance(tool, dict) and tool.get("type") == "image_generation" for tool in tools)


def has_web_search_tool(tools: list[dict[str, Any]]) -> bool:
    return any(isinstance(tool, dict) and tool.get("type") == "web_search" for tool in tools)


def _provider_native_web_search_enabled(request_options: dict[str, Any] | None) -> bool:
    if not isinstance(request_options, dict):
        return False
    value = request_options.get("_paper_notes_native_web_search", request_options.get("_paper_notes_provider_native_web_search"))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _merge_include(current: Any, values: list[str]) -> list[str]:
    items: list[str] = []
    if isinstance(current, str):
        items.append(current)
    elif isinstance(current, list):
        items.extend(str(item) for item in current if str(item or "").strip())
    for value in values:
        if value not in items:
            items.append(value)
    return items


def _work_trace_enabled(request_options: dict[str, Any] | None, *, provider_name: str) -> bool:
    if provider_name not in {"openai", CODEX_PROVIDER_NAME}:
        return False
    if not isinstance(request_options, dict):
        return True
    value = request_options.get("_paper_notes_work_trace", request_options.get("work_trace"))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return True


def _reasoning_effort_is_none(payload: dict[str, Any]) -> bool:
    reasoning = payload.get("reasoning")
    if not isinstance(reasoning, dict):
        return False
    return str(reasoning.get("effort") or "").strip().lower() == "none"


def preflight_codex_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Codex Responses request must be a dict.")

    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Codex Responses request 'model' must be a non-empty string.")

    store = payload.get("store", False)
    if store is not False:
        raise ValueError("Codex Responses contract requires 'store' to be false.")

    normalized: dict[str, Any] = {
        "model": model.strip(),
        "instructions": stringify_content(payload.get("instructions", "")),
        "input": preflight_codex_input_items(payload.get("input")),
        "store": False,
    }

    tools = payload.get("tools")
    if tools is not None:
        normalized["tools"] = preflight_codex_tools(tools)

    for key in (
        "reasoning",
        "include",
        "max_output_tokens",
        "temperature",
        "tool_choice",
        "parallel_tool_calls",
        "prompt_cache_key",
        "service_tier",
        "extra_headers",
    ):
        if key in payload and payload[key] is not None:
            normalized[key] = payload[key]

    allowed_keys = set(normalized) | {
        "model",
        "instructions",
        "input",
        "tools",
        "store",
        "reasoning",
        "include",
        "max_output_tokens",
        "temperature",
        "tool_choice",
        "parallel_tool_calls",
        "prompt_cache_key",
        "service_tier",
        "extra_headers",
    }
    unexpected = sorted(key for key in payload if key not in allowed_keys)
    if unexpected:
        raise ValueError(f"Codex Responses request has unsupported field(s): {', '.join(unexpected)}.")
    return normalized


def preflight_codex_input_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        raise ValueError("Codex Responses input must be a list of input items.")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise ValueError(f"Codex Responses input[{index}] must be an object.")

        item_type = item.get("type")
        if item_type == "function_call":
            normalized.append(_preflight_function_call_item(item, index))
            continue
        if item_type == "function_call_output":
            normalized.append(_preflight_function_call_output_item(item, index))
            continue
        if item_type == "reasoning":
            reasoning = _preflight_reasoning_item(item, seen_ids)
            if reasoning:
                normalized.append(reasoning)
            continue
        if item_type == "message":
            normalized.append(_preflight_message_item(item, index))
            continue

        role = item.get("role")
        if role in {"user", "assistant"}:
            normalized.append(_preflight_role_item(item, index, role=str(role)))
            continue

        raise ValueError(
            f"Codex Responses input[{index}] has unsupported item shape (type={item_type!r}, role={role!r})."
        )
    return normalized


def preflight_codex_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        raise ValueError("Codex Responses request 'tools' must be a list when provided.")
    normalized: list[dict[str, Any]] = []
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            raise ValueError(f"Codex Responses tools[{index}] must be an object.")
        tool_type = tool.get("type")
        if tool_type in {"image_generation", "web_search"}:
            normalized.append(dict(tool))
            continue
        if tool_type != "function":
            raise ValueError(f"Codex Responses tools[{index}] has unsupported type {tool_type!r}.")
        name = tool.get("name")
        parameters = tool.get("parameters")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Codex Responses tools[{index}] is missing a valid name.")
        if not isinstance(parameters, dict):
            raise ValueError(f"Codex Responses tools[{index}] is missing valid parameters.")
        normalized.append({
            "type": "function",
            "name": name.strip(),
            "description": stringify_content(tool.get("description", "")),
            "strict": bool(tool.get("strict", False)),
            "parameters": parameters,
        })
    return normalized


def normalize_responses_response(
    response: Any,
    *,
    request: ModelRequest | None,
    model: str,
    provider_name: str,
) -> ModelResponse:
    output_items = iter_output_items(response)
    if not output_items:
        output_text = get_attr(response, "output_text", "")
        if isinstance(output_text, str) and output_text.strip():
            output_items = [{
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": output_text.strip()}],
            }]

    response_status = normalize_status(get_attr(response, "status", ""))
    content_parts: list[str] = []
    reasoning_items: list[dict[str, Any]] = []
    message_items: list[dict[str, Any]] = []
    work_trace_items: list[dict[str, Any]] = []
    tool_calls: list[ToolCall] = []
    has_incomplete_items = response_status in _INCOMPLETE_STATUSES
    saw_commentary_phase = False
    saw_final_phase = False

    for item in output_items:
        item_type = str(get_attr(item, "type", "") or "")
        item_status = normalize_status(get_attr(item, "status", ""))
        if item_status in _INCOMPLETE_STATUSES:
            has_incomplete_items = True
        if item_type == "message":
            phase = normalize_phase(get_attr(item, "phase", ""))
            is_commentary_phase = phase in {"commentary", "analysis"}
            if is_commentary_phase:
                saw_commentary_phase = True
            elif phase in {"final_answer", "final"}:
                saw_final_phase = True
            message_text = extract_message_text(item)
            if message_text:
                raw_message = {
                    "type": "message",
                    "role": "assistant",
                    "status": normalize_responses_message_status(item_status),
                    "content": [{"type": "output_text", "text": message_text}],
                }
                item_id = get_attr(item, "id", None)
                if isinstance(item_id, str) and item_id:
                    raw_message["id"] = item_id
                if phase:
                    raw_message["phase"] = phase
                message_items.append(raw_message)
                if is_commentary_phase:
                    work_trace_items.append({
                        "type": "commentary",
                        "text": message_text,
                        "source": "provider",
                    })
                else:
                    content_parts.append(message_text)
            continue
        if item_type == "reasoning":
            reasoning = reasoning_item_for_replay(item)
            if reasoning:
                reasoning_items.append(reasoning)
                for summary_text in reasoning_summary_texts(reasoning):
                    work_trace_items.append({
                        "type": "summary",
                        "text": summary_text,
                        "source": "provider",
                    })
            continue
        if item_type in {"function_call", "custom_tool_call"}:
            if item_status in _INCOMPLETE_STATUSES:
                continue
            tool_call = tool_call_from_output_item(item, index=len(tool_calls), custom=item_type == "custom_tool_call")
            if tool_call is not None:
                tool_calls.append(tool_call)

    content = "\n".join(part for part in content_parts if part).strip()
    if not content:
        output_text = get_attr(response, "output_text", "")
        if isinstance(output_text, str):
            content = output_text.strip()

    leaked_tool_call_text = False
    if content and not tool_calls and _TOOL_CALL_LEAK_PATTERN.search(content):
        leaked_tool_call_text = True
        logger.warning("Responses output contained leaked tool-call text; treating it as incomplete.")
        content = ""

    incomplete_reason = incomplete_reason_from_response(response)
    if tool_calls:
        finish_reason = "tool_calls"
    elif leaked_tool_call_text:
        finish_reason = "incomplete"
        incomplete_reason = incomplete_reason or "leaked_tool_call_text"
    elif has_incomplete_items or (saw_commentary_phase and not saw_final_phase):
        finish_reason = "incomplete"
    elif reasoning_items and not content:
        finish_reason = "incomplete"
        incomplete_reason = incomplete_reason or "reasoning_only"
    else:
        finish_reason = finish_reason_from_status(response_status, response)

    provider_data = {
        "response_id": get_attr(response, "id", None),
        "status": response_status or None,
        "incomplete_reason": incomplete_reason,
        "codex_reasoning_items": reasoning_items or None,
        "codex_message_items": message_items or None,
        "work_trace_items": work_trace_items or None,
        "leaked_tool_call_text": leaked_tool_call_text or None,
        **web_search_metadata_from_response(response),
    }

    return ModelResponse(
        content=content or None,
        tool_calls=tool_calls,
        artifacts=image_artifacts_from_response(response, request=request, model=model, provider_name=provider_name),
        finish_reason=finish_reason,
        usage=usage_from_response(response),
        provider_data={key: value for key, value in provider_data.items() if value not in (None, False, "", [])} or None,
    )


def assistant_tool_calls_to_response_items(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
        name = function.get("name") or tool_call.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        embedded_call_id, embedded_response_item_id = split_responses_tool_id(tool_call.get("id"))
        call_id = tool_call.get("call_id")
        if not isinstance(call_id, str) or not call_id.strip():
            call_id = embedded_call_id
        if not isinstance(call_id, str) or not call_id.strip():
            response_item_id = tool_call.get("response_item_id") or embedded_response_item_id
            if isinstance(response_item_id, str) and response_item_id.startswith("fc_"):
                call_id = f"call_{response_item_id[len('fc_'):]}"
            else:
                call_id = deterministic_call_id(name, stringify_content(function.get("arguments", "{}")), index)
        arguments = function.get("arguments", tool_call.get("arguments", "{}"))
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        else:
            arguments = stringify_content(arguments) or "{}"
        items.append({
            "type": "function_call",
            "call_id": call_id.strip(),
            "name": name.strip(),
            "arguments": arguments,
        })
    return items


def tool_call_from_output_item(item: Any, *, index: int, custom: bool = False) -> ToolCall | None:
    name = get_attr(item, "name", None)
    if not isinstance(name, str) or not name.strip():
        return None
    raw_arguments = get_attr(item, "input", "{}") if custom else get_attr(item, "arguments", "{}")
    if isinstance(raw_arguments, dict | list):
        arguments = json.dumps(raw_arguments, ensure_ascii=False)
    else:
        arguments = stringify_content(raw_arguments) or "{}"
    raw_call_id = get_attr(item, "call_id", None)
    raw_item_id = get_attr(item, "id", None)
    embedded_call_id, embedded_response_item_id = split_responses_tool_id(raw_item_id)
    call_id = raw_call_id if isinstance(raw_call_id, str) and raw_call_id.strip() else embedded_call_id
    if not isinstance(call_id, str) or not call_id.strip():
        call_id = deterministic_call_id(name, arguments, index)
    call_id = call_id.strip()
    response_item_id = raw_item_id if isinstance(raw_item_id, str) and raw_item_id.strip() else embedded_response_item_id
    response_item_id = derive_responses_function_call_id(call_id, response_item_id)
    return ToolCall(
        id=call_id,
        name=name.strip(),
        arguments=arguments,
        provider_data={"call_id": call_id, "response_item_id": response_item_id},
    )


def deterministic_call_id(function_name: str, arguments: str, index: int = 0) -> str:
    seed = f"{function_name}:{arguments}:{index}"
    digest = hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"call_{digest}"


def split_responses_tool_id(raw_id: Any) -> tuple[str | None, str | None]:
    if not isinstance(raw_id, str):
        return None, None
    value = raw_id.strip()
    if not value:
        return None, None
    if "|" in value:
        call_id, response_item_id = value.split("|", 1)
        return call_id.strip() or None, response_item_id.strip() or None
    if value.startswith("fc_"):
        return None, value
    return value, None


def derive_responses_function_call_id(call_id: str, response_item_id: str | None = None) -> str:
    if isinstance(response_item_id, str):
        candidate = response_item_id.strip()
        if candidate.startswith("fc_"):
            return candidate
    source = (call_id or "").strip()
    if source.startswith("fc_"):
        return source
    if source.startswith("call_") and len(source) > len("call_"):
        return f"fc_{source[len('call_'):]}"
    sanitized = re.sub(r"[^A-Za-z0-9_-]", "", source)
    if sanitized.startswith("fc_"):
        return sanitized
    if sanitized.startswith("call_") and len(sanitized) > len("call_"):
        return f"fc_{sanitized[len('call_'):]}"
    if sanitized:
        return f"fc_{sanitized[:48]}"
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:24]
    return f"fc_{digest}"


def image_artifacts_from_response(
    response: Any,
    *,
    request: ModelRequest | None,
    model: str,
    provider_name: str,
) -> list[dict[str, Any]]:
    if request is None:
        return []
    media_store = request.request_options.get("_paper_notes_media_store")
    if media_store is None:
        return []
    create_generated_image = getattr(media_store, "create_generated_image", None)
    if not callable(create_generated_image):
        return []
    session_id = str(request.request_options.get("_paper_notes_session_id") or "")
    resolved_provider = str(request.request_options.get("_paper_notes_provider") or provider_name)
    generation_options = request.request_options.get("_paper_notes_image_generation")
    if not isinstance(generation_options, dict):
        generation_options = {}
    artifacts: list[dict[str, Any]] = []
    for item in iter_output_items(response):
        if str(get_attr(item, "type", "") or "") != "image_generation_call":
            continue
        result = get_attr(item, "result", None)
        if not isinstance(result, str) or not result:
            continue
        artifact = create_generated_image(
            result,
            session_id=session_id,
            provider=resolved_provider,
            model=model,
            file_format=str(generation_options.get("format") or "png"),
            metadata={
                "response_id": get_attr(response, "id", None),
                "generation_call_id": get_attr(item, "id", None),
                "revised_prompt": get_attr(item, "revised_prompt", None),
                "size": generation_options.get("size"),
                "quality": generation_options.get("quality"),
            },
        )
        to_dict = getattr(artifact, "to_dict", None)
        artifacts.append(to_dict() if callable(to_dict) else dict(artifact))
    return artifacts


def web_search_metadata_from_response(response: Any) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    citations: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for item in iter_output_items(response):
        item_type = str(get_attr(item, "type", "") or "")
        if item_type == "web_search_call":
            call = {
                "id": get_attr(item, "id", None),
                "status": get_attr(item, "status", None),
                "action": _jsonable(get_attr(item, "action", None)),
            }
            calls.append({key: value for key, value in call.items() if value not in (None, "", [], {})})
            for source in _sources_from_action(get_attr(item, "action", None)):
                if _add_source(source, sources=sources, seen_urls=seen_urls):
                    continue
        if item_type != "message":
            continue
        content = get_attr(item, "content", None)
        if not isinstance(content, list):
            continue
        for part in content:
            for annotation in _annotation_items(get_attr(part, "annotations", None)):
                citation = _citation_from_annotation(annotation)
                if citation:
                    citations.append(citation)
                    source = {
                        "title": str(citation.get("title") or ""),
                        "url": str(citation.get("url") or ""),
                        "snippet": str(citation.get("snippet") or ""),
                    }
                    _add_source(source, sources=sources, seen_urls=seen_urls)

    return {
        "web_search_calls": calls or None,
        "web_search_sources": sources or None,
        "web_search_citations": citations or None,
    }


def _sources_from_action(action: Any) -> list[dict[str, str]]:
    raw_sources = get_attr(action, "sources", None)
    if not isinstance(raw_sources, list):
        return []
    sources: list[dict[str, str]] = []
    for source in raw_sources:
        url = str(get_attr(source, "url", "") or "").strip()
        if not url:
            continue
        sources.append({
            "title": str(get_attr(source, "title", "") or "").strip(),
            "url": url,
            "snippet": str(get_attr(source, "snippet", "") or get_attr(source, "text", "") or "").strip(),
        })
    return sources


def _annotation_items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _citation_from_annotation(annotation: Any) -> dict[str, Any]:
    annotation_type = str(get_attr(annotation, "type", "") or "")
    if annotation_type not in {"url_citation", "citation"}:
        return {}
    url = str(get_attr(annotation, "url", "") or "").strip()
    if not url:
        return {}
    citation: dict[str, Any] = {
        "title": str(get_attr(annotation, "title", "") or "").strip(),
        "url": url,
        "snippet": str(get_attr(annotation, "snippet", "") or "").strip(),
    }
    for field in ("start_index", "end_index"):
        value = get_attr(annotation, field, None)
        if isinstance(value, int):
            citation[field] = value
    return {key: value for key, value in citation.items() if value not in ("", None)}


def _add_source(source: dict[str, str], *, sources: list[dict[str, str]], seen_urls: set[str]) -> bool:
    url = str(source.get("url") or "").strip()
    if not url or url in seen_urls:
        return False
    seen_urls.add(url)
    sources.append({
        "title": str(source.get("title") or "").strip(),
        "url": url,
        "snippet": str(source.get("snippet") or "").strip(),
    })
    return True


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {str(key): _jsonable(item) for key, item in vars(value).items() if not str(key).startswith("_")}
    return str(value)


def usage_from_response(response: Any) -> TokenUsage | None:
    usage = get_attr(response, "usage", None)
    if usage is None:
        return None
    input_tokens = int(get_attr(usage, "input_tokens", 0) or 0)
    output_tokens = int(get_attr(usage, "output_tokens", 0) or 0)
    total_tokens = int(get_attr(usage, "total_tokens", 0) or input_tokens + output_tokens)
    return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens)


def extract_message_text(item: Any) -> str:
    content = get_attr(item, "content", None)
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for part in content:
        part_type = str(get_attr(part, "type", "") or "")
        if part_type not in {"output_text", "text"}:
            continue
        text = get_attr(part, "text", None)
        if isinstance(text, str) and text:
            chunks.append(text)
    return "".join(chunks).strip()


def reasoning_item_for_replay(item: Any) -> dict[str, Any] | None:
    encrypted = get_attr(item, "encrypted_content", None)
    if not isinstance(encrypted, str) or not encrypted:
        return None
    raw_item: dict[str, Any] = {"type": "reasoning", "encrypted_content": encrypted}
    item_id = get_attr(item, "id", None)
    if isinstance(item_id, str) and item_id:
        raw_item["id"] = item_id
    summary = get_attr(item, "summary", None)
    raw_summary: list[dict[str, str]] = []
    if isinstance(summary, list):
        for part in summary:
            text = get_attr(part, "text", None)
            if isinstance(text, str):
                raw_summary.append({"type": "summary_text", "text": text})
    raw_item["summary"] = raw_summary
    return raw_item


def reasoning_summary_texts(item: dict[str, Any]) -> list[str]:
    summary = item.get("summary")
    if not isinstance(summary, list):
        return []
    texts: list[str] = []
    for part in summary:
        if not isinstance(part, dict):
            continue
        text = stringify_content(part.get("text", "")).strip()
        if text:
            texts.append(text)
    return texts


def iter_output_items(response: Any) -> list[Any]:
    output = get_attr(response, "output", None)
    return output if isinstance(output, list) else []


def finish_reason_from_status(status: str, response: Any) -> str:
    if status == "incomplete":
        details = get_attr(response, "incomplete_details", None)
        reason = get_attr(details, "reason", "") if details is not None else ""
        return "length" if reason == "max_output_tokens" else "incomplete"
    if status in {"failed", "cancelled"}:
        return status
    return "stop"


def incomplete_reason_from_response(response: Any) -> str:
    details = get_attr(response, "incomplete_details", None)
    reason = get_attr(details, "reason", "") if details is not None else ""
    return str(reason or "").strip()


def normalize_responses_message_status(value: Any, *, default: str = "completed") -> str:
    status = normalize_status(value)
    return status if status in _RESPONSE_MESSAGE_STATUSES else default


def normalize_status(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower().replace("-", "_").replace(" ", "_")
    return ""


def normalize_phase(value: Any) -> str:
    return normalize_status(value)


def stringify_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def get_attr(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def attachment_items(attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(attachments, list):
        return []
    return [item for item in attachments if isinstance(item, dict)]


def attachment_is_image(attachment: dict[str, Any]) -> bool:
    kind = str(attachment.get("kind") or "").strip().lower()
    mime_type = str(attachment.get("mimeType") or attachment.get("mime_type") or "").strip().lower()
    return kind == "image" or mime_type.startswith("image/")


def attachment_data_url(attachment: dict[str, Any], media_store: Any) -> str:
    direct_url = str(attachment.get("image_url") or attachment.get("imageUrl") or "")
    if direct_url.startswith("data:image/"):
        return direct_url
    artifact_id = str(attachment.get("id") or attachment.get("artifactId") or "")
    if not artifact_id or media_store is None:
        return ""
    data_url_for_artifact = getattr(media_store, "data_url_for_artifact", None)
    if not callable(data_url_for_artifact):
        return ""
    return str(data_url_for_artifact(artifact_id) or "")


def attachment_text(attachment: dict[str, Any], media_store: Any) -> str:
    artifact_id = str(attachment.get("id") or attachment.get("artifactId") or "")
    if not artifact_id or media_store is None:
        return ""
    extracted_text_for_artifact = getattr(media_store, "extracted_text_for_artifact", None)
    if not callable(extracted_text_for_artifact):
        return ""
    text = stringify_content(extracted_text_for_artifact(artifact_id)).strip()
    if not text:
        return ""
    file_name = stringify_content(attachment.get("fileName") or attachment.get("file_name") or artifact_id).strip()
    return f"Attachment: {file_name}\n\n{text}" if file_name else text


def _append_assistant_replay_items(
    input_items: list[dict[str, Any]],
    message: dict[str, Any],
    seen_item_ids: set[str],
) -> None:
    codex_reasoning = message.get("codex_reasoning_items")
    if isinstance(codex_reasoning, list):
        for item in codex_reasoning:
            if not isinstance(item, dict) or not item.get("encrypted_content"):
                continue
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id in seen_item_ids:
                continue
            replay_item = {key: value for key, value in item.items() if key != "id"}
            input_items.append(replay_item)
            if isinstance(item_id, str) and item_id:
                seen_item_ids.add(item_id)

    codex_messages = message.get("codex_message_items")
    if isinstance(codex_messages, list):
        for raw_item in codex_messages:
            replay_item = _normalize_replay_message_item(raw_item)
            if replay_item is not None:
                input_items.append(replay_item)


def _normalize_replay_message_item(raw_item: Any) -> dict[str, Any] | None:
    if not isinstance(raw_item, dict):
        return None
    if raw_item.get("type") != "message" or raw_item.get("role") != "assistant":
        return None
    content = raw_item.get("content")
    if not isinstance(content, list):
        return None
    normalized_content: list[dict[str, str]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "").strip()
        if part_type not in {"output_text", "text"}:
            continue
        text = part.get("text", "")
        normalized_content.append({"type": "output_text", "text": stringify_content(text)})
    if not normalized_content:
        return None
    replay_item: dict[str, Any] = {
        "type": "message",
        "role": "assistant",
        "status": normalize_responses_message_status(raw_item.get("status")),
        "content": normalized_content,
    }
    item_id = raw_item.get("id")
    if isinstance(item_id, str) and item_id.strip():
        replay_item["id"] = item_id.strip()
    phase = raw_item.get("phase")
    if isinstance(phase, str) and phase.strip():
        replay_item["phase"] = phase.strip()
    return replay_item


def _has_replayed_message_items(message: dict[str, Any]) -> bool:
    codex_messages = message.get("codex_message_items")
    return isinstance(codex_messages, list) and any(_normalize_replay_message_item(item) for item in codex_messages)


def _has_codex_reasoning_items(message: dict[str, Any]) -> bool:
    codex_reasoning = message.get("codex_reasoning_items")
    return isinstance(codex_reasoning, list) and any(
        isinstance(item, dict) and bool(item.get("encrypted_content")) for item in codex_reasoning
    )


def _preflight_function_call_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    call_id = item.get("call_id")
    name = item.get("name")
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError(f"Codex Responses input[{index}] function_call is missing call_id.")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Codex Responses input[{index}] function_call is missing name.")
    arguments = item.get("arguments", "{}")
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments, ensure_ascii=False)
    else:
        arguments = stringify_content(arguments) or "{}"
    return {
        "type": "function_call",
        "call_id": call_id.strip(),
        "name": name.strip(),
        "arguments": arguments,
    }


def _preflight_function_call_output_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    call_id = item.get("call_id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError(f"Codex Responses input[{index}] function_call_output is missing call_id.")
    return {
        "type": "function_call_output",
        "call_id": call_id.strip(),
        "output": stringify_content(item.get("output", "")),
    }


def _preflight_reasoning_item(item: dict[str, Any], seen_ids: set[str]) -> dict[str, Any] | None:
    encrypted = item.get("encrypted_content")
    if not isinstance(encrypted, str) or not encrypted:
        return None
    item_id = item.get("id")
    if isinstance(item_id, str) and item_id:
        if item_id in seen_ids:
            return None
        seen_ids.add(item_id)
    summary = item.get("summary")
    return {
        "type": "reasoning",
        "encrypted_content": encrypted,
        "summary": summary if isinstance(summary, list) else [],
    }


def _preflight_message_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    if item.get("role") != "assistant":
        raise ValueError(f"Codex Responses input[{index}] message items must have role='assistant'.")
    content = item.get("content")
    if not isinstance(content, list):
        raise ValueError(f"Codex Responses input[{index}] message item must have content list.")
    normalized_content = _preflight_content_parts(content, index, role="assistant")
    if not normalized_content:
        raise ValueError(f"Codex Responses input[{index}] message item must contain at least one text part.")
    normalized_item: dict[str, Any] = {
        "type": "message",
        "role": "assistant",
        "status": normalize_responses_message_status(item.get("status")),
        "content": normalized_content,
    }
    item_id = item.get("id")
    if isinstance(item_id, str) and item_id.strip():
        normalized_item["id"] = item_id.strip()
    phase = item.get("phase")
    if isinstance(phase, str) and phase.strip():
        normalized_item["phase"] = phase.strip()
    return normalized_item


def _preflight_role_item(item: dict[str, Any], index: int, *, role: str) -> dict[str, Any]:
    content = item.get("content", "")
    if isinstance(content, list):
        return {
            "role": role,
            "content": _preflight_content_parts(content, index, role=role),
        }
    return {
        "role": role,
        "content": stringify_content(content),
    }


def _preflight_content_parts(content: list[Any], index: int, *, role: str) -> list[dict[str, Any]]:
    text_type = "output_text" if role == "assistant" else "input_text"
    validated: list[dict[str, Any]] = []
    for part_index, part in enumerate(content):
        if isinstance(part, str):
            if part:
                validated.append({"type": text_type, "text": part})
            continue
        if not isinstance(part, dict):
            raise ValueError(f"Codex Responses input[{index}].content[{part_index}] must be an object or string.")
        part_type = str(part.get("type") or "").strip().lower()
        if part_type in {"input_text", "output_text", "text"}:
            validated.append({"type": text_type, "text": stringify_content(part.get("text", ""))})
            continue
        if part_type in {"input_image", "image_url"}:
            image_ref = part.get("image_url", "")
            detail = part.get("detail")
            if isinstance(image_ref, dict):
                detail = image_ref.get("detail", detail)
                image_ref = image_ref.get("url", "")
            image_part: dict[str, Any] = {"type": "input_image", "image_url": stringify_content(image_ref)}
            if isinstance(detail, str) and detail.strip():
                image_part["detail"] = detail.strip()
            validated.append(image_part)
            continue
        raise ValueError(
            f"Codex Responses input[{index}].content[{part_index}] has unsupported type {part.get('type')!r}."
        )
    return validated
