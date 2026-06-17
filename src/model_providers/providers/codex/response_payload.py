from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from app_infra.artifact_generation import truthy_option
from model_providers.providers.codex.response_common import (
    combine_instructions as _combine_instructions,
    content_text as _content_text,
    image_generation_options as _image_generation_options,
    merge_include as _merge_include,
)

__all__ = [
    "codex_tool_spec",
    "create_responses_response",
    "responses_payload",
]

CODEX_RESPONSES_OPTIONS = {
    "include",
    "parallel_tool_calls",
    "prompt_cache_key",
    "reasoning",
    "service_tier",
    "text",
    "top_p",
    "truncation",
}


def _create_responses_response(client: Any, payload: dict[str, Any]) -> Any:
    create = getattr(getattr(client, "responses", None), "create", None)
    if not callable(create):
        raise RuntimeError("Codex Responses client does not provide responses.create.")
    return create(**payload)


def _responses_payload(
    messages: list[BaseMessage],
    *,
    model: str,
    options: dict[str, Any],
    tools: list[dict[str, Any]],
    tool_choice: str | None,
) -> dict[str, Any]:
    instructions, input_items = _messages_to_responses_input(messages)
    payload: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "store": False,
    }
    resolved_instructions = _combine_instructions(
        instructions,
        _host_tool_instructions(tools, tool_choice=tool_choice) if tools else "",
        str(options.get("developer_instructions") or ""),
        str(options.get("base_instructions") or ""),
    )
    if resolved_instructions:
        payload["instructions"] = resolved_instructions

    response_tools = _responses_tools(tools)
    if _native_web_search_enabled(options):
        response_tools.append({"type": "web_search"})
    image_generation_tool = _image_generation_tool(options) if _native_image_generation_enabled(options) else None
    if image_generation_tool:
        response_tools.append(image_generation_tool)
    if response_tools:
        payload["tools"] = response_tools
        payload["tool_choice"] = _responses_tool_choice(tool_choice)

    reasoning = _responses_reasoning(options)
    if reasoning:
        payload["reasoning"] = reasoning
        payload["include"] = _merge_include(payload.get("include"), ["reasoning.encrypted_content"])

    for key in CODEX_RESPONSES_OPTIONS:
        value = options.get(key)
        if value is not None and key not in payload:
            payload[key] = value
    if "max_output_tokens" in options:
        # The ChatGPT-account Codex backend has historically rejected max_output_tokens.
        pass
    return payload


def _messages_to_responses_input(messages: list[BaseMessage]) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in messages:
        role = str(getattr(message, "type", "") or "").strip()
        raw_content = getattr(message, "content", "")
        content = _content_text(raw_content)
        if role in {"system", "developer"}:
            if content:
                instructions.append(content)
            continue
        if role == "human":
            input_items.append({"role": "user", "content": _responses_message_content(raw_content)})
            continue
        if role == "ai":
            if content:
                input_items.append({"role": "assistant", "content": content})
            input_items.extend(_assistant_tool_calls_to_response_items(getattr(message, "tool_calls", None) or []))
            continue
        if role == "tool":
            call_id = str(getattr(message, "tool_call_id", "") or "").strip()
            if call_id:
                input_items.append({"type": "function_call_output", "call_id": call_id, "output": content})
            continue
        if content:
            input_items.append({"role": "user", "content": content})
    if not input_items:
        input_items.append({"role": "user", "content": ""})
    return "\n\n".join(part for part in instructions if part).strip(), input_items


def _responses_message_content(content: Any) -> str | list[dict[str, Any]]:
    if not isinstance(content, list):
        return _content_text(content)
    parts: list[dict[str, Any]] = []
    for item in content:
        converted = _responses_content_part(item)
        if converted:
            parts.append(converted)
    return parts or _content_text(content)


def _responses_content_part(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        return {"type": "input_text", "text": item}
    if not isinstance(item, dict):
        text = str(item) if item is not None else ""
        return {"type": "input_text", "text": text} if text else None

    part_type = str(item.get("type") or "").strip()
    if part_type in {"text", "input_text"}:
        text = item.get("text", item.get("content", ""))
        return {"type": "input_text", "text": str(text)} if text is not None else None
    if part_type in {"image_url", "input_image"}:
        image_url = _image_url_from_part(item)
        if image_url:
            return {"type": "input_image", "image_url": image_url}

    text = item.get("text", item.get("content", ""))
    if isinstance(text, str) and text:
        return {"type": "input_text", "text": text}
    return None


def _image_url_from_part(item: dict[str, Any]) -> str:
    value = item.get("image_url") or item.get("imageUrl") or item.get("url")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("url") or value.get("image_url") or value.get("imageUrl") or "")
    return ""


def _host_tool_instructions(tools: list[dict[str, Any]], *, tool_choice: str | None) -> str:
    names = ", ".join(str(tool.get("name") or "") for tool in tools if str(tool.get("name") or ""))
    choice = str(tool_choice or "").strip()
    choice_instruction = ""
    if choice == "any":
        choice_instruction = " You must call one of these host tools before answering."
    elif choice and choice not in {"auto", "none"}:
        choice_instruction = f" Prefer the host tool named {choice!r} when a tool is needed."
    return (
        "Paper Notes host tools are provided as Responses function tools in this request. "
        "Use only these function tools for local notes, paper source material, annotations, and note edits. "
        "Do not use or try to discover Codex built-in tools, MCP resources, shell commands, browser tools, "
        "plugins, workspace tools, dynamic tools, or list_mcp_resources/read_mcp_resource style tools. "
        "Do not call any MCP server such as local-paper-notes or codex to inspect available tools. "
        "The complete Paper Notes tool catalog for this request is already present in the tools array"
        f"{f' ({names})' if names else ''}.{choice_instruction}"
    )


def _codex_tool_spec(tool: dict[str, Any] | type | Callable | BaseTool) -> dict[str, Any]:
    converted = convert_to_openai_tool(tool)
    function = converted.get("function") if isinstance(converted, dict) else None
    if not isinstance(function, dict):
        return converted if isinstance(converted, dict) else {}
    return {
        "name": str(function.get("name") or ""),
        "description": str(function.get("description") or ""),
        "parameters": function.get("parameters") if isinstance(function.get("parameters"), dict) else {"type": "object"},
        **({"strict": bool(function["strict"])} if "strict" in function else {}),
    }


def _responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        tool_type = str(tool.get("type") or "").strip()
        if tool_type and tool_type != "function":
            converted.append(dict(tool))
            continue
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        converted.append({
            "type": "function",
            "name": name,
            "description": str(tool.get("description") or ""),
            "parameters": tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {"type": "object"},
            **({"strict": bool(tool["strict"])} if "strict" in tool else {}),
        })
    return converted


def _responses_tool_choice(tool_choice: str | None) -> Any:
    choice = str(tool_choice or "auto").strip()
    if choice in {"", "auto"}:
        return "auto"
    if choice == "none":
        return "none"
    if choice == "any":
        return "required"
    return {"type": "function", "name": choice}


def _responses_reasoning(options: dict[str, Any]) -> dict[str, Any]:
    reasoning = options.get("reasoning")
    payload = dict(reasoning) if isinstance(reasoning, dict) else {}
    effort = options.get("effort", options.get("reasoning_effort"))
    summary = options.get("summary")
    if effort is not None:
        payload["effort"] = effort
    if summary is not None:
        payload["summary"] = summary
    if payload and str(payload.get("effort") or "").strip().lower() != "none":
        payload.setdefault("summary", "auto")
    return payload


def _native_web_search_enabled(options: dict[str, Any]) -> bool:
    for key in ("native_web_search", "web_search", "_paper_notes_native_web_search"):
        value = options.get(key)
        if isinstance(value, bool | str):
            return truthy_option(value)
    return False


def _native_image_generation_enabled(options: dict[str, Any]) -> bool:
    return truthy_option(options.get("_paper_notes_codex_native_image_generation"))


def _image_generation_tool(options: dict[str, Any]) -> dict[str, Any] | None:
    config = _image_generation_options(options)
    if not config:
        return None
    tool: dict[str, Any] = {"type": "image_generation"}
    for source_key, target_key in (
        ("model", "model"),
        ("size", "size"),
        ("quality", "quality"),
        ("background", "background"),
        ("moderation", "moderation"),
        ("partial_images", "partial_images"),
        ("partialImages", "partial_images"),
    ):
        value = config.get(source_key)
        if value not in (None, "", []):
            tool[target_key] = value
    output_format = config.get("output_format", config.get("outputFormat", config.get("format")))
    if output_format not in (None, "", []):
        tool["output_format"] = str(output_format)
    return tool


def _assistant_tool_calls_to_response_items(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            continue
        name = str(tool_call.get("name") or "").strip()
        if not name:
            continue
        args = tool_call.get("args", {})
        arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False, separators=(",", ":"))
        items.append({
            "type": "function_call",
            "call_id": str(tool_call.get("id") or f"call_{uuid.uuid4().hex[:12]}_{index}"),
            "name": name,
            "arguments": arguments or "{}",
        })
    return items


create_responses_response = _create_responses_response
codex_tool_spec = _codex_tool_spec
responses_payload = _responses_payload

