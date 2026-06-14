from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import uuid
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from openai import OpenAI
from pydantic import Field

from model_providers.core.types import ModelProviderConfig


CODEX_PROVIDER_NAME = "codex-oauth"
DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120
CODEX_CLIENT_HEADERS = {
    "User-Agent": "codex_cli_rs/0.0.0 (Paper Notes)",
    "originator": "codex_cli_rs",
}
CODEX_AUTH_PATH_ENV = "PAPER_NOTES_CODEX_AUTH_PATH"
CODEX_RESPONSES_OPTIONS = {
    "include",
    "parallel_tool_calls",
    "prompt_cache_key",
    "reasoning",
    "service_tier",
    "temperature",
    "text",
    "top_p",
    "truncation",
}


@dataclass(frozen=True, slots=True)
class _CodexCredentials:
    access_token: str = ""
    refresh_token: str = ""
    id_token: str = ""
    account_id: str = ""
    base_url: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.access_token or self.refresh_token)


class CodexChatModel(BaseChatModel):
    model: str
    options: dict[str, Any] = Field(default_factory=dict)
    bound_tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: str | None = None
    client: Any | None = Field(default=None, exclude=True)

    @property
    def _llm_type(self) -> str:
        return "openai-codex-responses"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> "CodexChatModel":
        options = {**self.options, **kwargs} if kwargs else dict(self.options)
        return self.model_copy(update={
            "options": options,
            "bound_tools": [_codex_tool_spec(tool) for tool in tools],
            "tool_choice": tool_choice,
        })

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager
        options = {**self.options, **kwargs}
        response = _create_responses_response(
            _codex_openai_client(options, explicit_client=self.client),
            _responses_payload(messages, model=self.model, options=options, tools=self.bound_tools, tool_choice=self.tool_choice),
        )
        message = _message_from_responses_response(response, options=options, model=self.model)
        return ChatResult(
            generations=[ChatGeneration(message=message, generation_info=dict(message.response_metadata or {}))],
            llm_output={"usage": message.response_metadata.get("usage") if isinstance(message.response_metadata, dict) else None},
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ):
        del stop, run_manager
        options = {**self.options, **kwargs}
        client = _codex_openai_client(options, explicit_client=self.client)
        payload = _responses_payload(messages, model=self.model, options=options, tools=self.bound_tools, tool_choice=self.tool_choice)
        stream_factory = getattr(getattr(client, "responses", None), "stream", None)
        if not callable(stream_factory):
            result = self._generate(messages, **kwargs)
            message = result.generations[0].message
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=str(message.content or ""),
                    tool_call_chunks=_tool_call_chunks_from_tool_calls(message.tool_calls),
                    chunk_position="last",
                    response_metadata=dict(message.response_metadata or {}),
                ),
                generation_info=result.generations[0].generation_info,
            )
            return

        streamed_content = False
        final_response: Any | None = None
        with stream_factory(**payload) as stream:
            for event in stream:
                for chunk in _stream_chunk_from_responses_event(event):
                    if str(chunk.message.content or ""):
                        streamed_content = True
                    yield chunk
            get_final_response = getattr(stream, "get_final_response", None)
            if callable(get_final_response):
                final_response = get_final_response()
        if final_response is None:
            raise RuntimeError("Codex Responses stream completed without a final response.")
        yield _final_generation_chunk_from_response(final_response, suppress_content=streamed_content, options=options, model=self.model)


def create_codex_chat_model(config: ModelProviderConfig) -> CodexChatModel:
    return CodexChatModel(model=config.model, options=dict(config.options))


def _codex_openai_client(options: dict[str, Any], *, explicit_client: Any | None = None) -> Any:
    if explicit_client is not None:
        return explicit_client
    credentials = _runtime_codex_credentials(auth_path=options.get("auth_path"))
    if not credentials.access_token:
        raise RuntimeError("Codex OAuth is not connected. Open Settings > AI Provider and connect Codex OAuth.")
    return OpenAI(
        api_key=credentials.access_token,
        base_url=str(options.get("base_url") or credentials.base_url or DEFAULT_CODEX_BASE_URL).rstrip("/"),
        default_headers=_codex_default_headers(credentials),
    )


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
    image_generation_tool = _image_generation_tool(options)
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
        content = _content_text(getattr(message, "content", ""))
        if role in {"system", "developer"}:
            if content:
                instructions.append(content)
            continue
        if role == "human":
            input_items.append({"role": "user", "content": content})
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
    for key in ("native_web_search", "web_search", "_paper_notes_native_web_search", "_paper_notes_provider_native_web_search"):
        value = options.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return False


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


def _image_generation_options(options: dict[str, Any]) -> dict[str, Any]:
    for key in ("_paper_notes_image_generation", "imageGeneration", "image_generation"):
        value = options.get(key)
        if not isinstance(value, dict):
            continue
        if value.get("enabled") is False:
            return {}
        if value.get("enabled") is True or any(name in value for name in ("size", "quality", "format", "output_format", "model")):
            return dict(value)
    return {}


def _message_from_responses_response(response: Any, *, options: dict[str, Any], model: str) -> AIMessage:
    content, tool_calls, info = _parse_responses_response(response, options=options, model=model)
    if not content and not tool_calls and not info.get("artifacts"):
        raise RuntimeError("Codex completed without a user-visible response.")
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


def _first_int(value: Any, *keys: str) -> int:
    for key in keys:
        raw = _get_attr(value, key, None)
        if isinstance(raw, bool):
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            return number
    return 0


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text", item.get("content", ""))
                if isinstance(text, str):
                    parts.append(text)
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content) if content is not None else ""


def _combine_instructions(*parts: str | None) -> str:
    return "\n\n".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def _merge_include(current: Any, values: list[str]) -> list[str]:
    items: list[str] = []
    if isinstance(current, str) and current.strip():
        items.append(current.strip())
    elif isinstance(current, list):
        items.extend(str(item) for item in current if str(item or "").strip())
    for value in values:
        if value not in items:
            items.append(value)
    return items


def _normalize_phase(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _get_attr(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(by_alias=True, mode="json"))
        except TypeError:
            return _json_safe(model_dump())
    return str(getattr(value, "value", value))


def _runtime_codex_credentials(*, auth_path: Any = None) -> _CodexCredentials:
    path = _codex_auth_path(auth_path)
    payload = _read_auth_payload(path)
    credentials = _credentials_from_auth_payload(payload)
    if credentials.refresh_token and _access_token_is_expiring(credentials.access_token):
        credentials = _refresh_codex_credentials(credentials)
        _write_refreshed_auth_payload(path, payload, credentials)
    return credentials


def _codex_auth_path(value: Any = None) -> Path:
    if value:
        return Path(str(value)).expanduser()
    override = os.environ.get(CODEX_AUTH_PATH_ENV, "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex" / "auth.json"


def _read_auth_payload(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _credentials_from_auth_payload(payload: dict[str, Any]) -> _CodexCredentials:
    tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {}
    return _CodexCredentials(
        access_token=str(tokens.get("access_token") or payload.get("accessToken") or payload.get("access_token") or ""),
        refresh_token=str(tokens.get("refresh_token") or payload.get("refreshToken") or payload.get("refresh_token") or ""),
        id_token=str(tokens.get("id_token") or payload.get("idToken") or payload.get("id_token") or ""),
        account_id=str(tokens.get("account_id") or payload.get("accountId") or payload.get("account_id") or ""),
        base_url=str(tokens.get("base_url") or payload.get("baseUrl") or payload.get("base_url") or DEFAULT_CODEX_BASE_URL),
    )


def _refresh_codex_credentials(credentials: _CodexCredentials) -> _CodexCredentials:
    status, payload = _post_form(
        CODEX_OAUTH_TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": credentials.refresh_token,
            "client_id": CODEX_OAUTH_CLIENT_ID,
        },
    )
    if status != 200:
        return credentials
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        return credentials
    return _CodexCredentials(
        access_token=access_token,
        refresh_token=str(payload.get("refresh_token") or credentials.refresh_token),
        id_token=str(payload.get("id_token") or credentials.id_token),
        account_id=credentials.account_id or _chatgpt_account_id(access_token),
        base_url=credentials.base_url or DEFAULT_CODEX_BASE_URL,
    )


def _write_refreshed_auth_payload(path: Path, original: dict[str, Any], credentials: _CodexCredentials) -> None:
    payload = dict(original)
    tokens = dict(payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {})
    tokens.update({
        "access_token": credentials.access_token,
        "refresh_token": credentials.refresh_token,
        "id_token": credentials.id_token,
        "account_id": credentials.account_id,
    })
    payload["tokens"] = tokens
    payload["last_refresh"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".codex_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _post_form(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    data = urlencode(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={**CODEX_CLIENT_HEADERS, "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, _parse_json(response.read())
    except HTTPError as error:
        return error.code, _parse_json(error.read())
    except OSError:
        return 0, {}


def _parse_json(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _access_token_is_expiring(token: str, skew_seconds: int = CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS) -> bool:
    if not token:
        return False
    exp = _jwt_claims(token).get("exp")
    try:
        expires_at = int(exp)
    except (TypeError, ValueError):
        return False
    return time.time() >= expires_at - skew_seconds


def _jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        claims = json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}


def _chatgpt_account_id(token: str) -> str:
    claims = _jwt_claims(token)
    for key in ("https://api.openai.com/auth", "chatgpt_account_id", "account_id"):
        value = claims.get(key)
        if isinstance(value, dict):
            account_id = value.get("chatgpt_account_id") or value.get("account_id")
            if account_id:
                return str(account_id)
        if isinstance(value, str) and value:
            return value
    return ""


def _codex_default_headers(credentials: _CodexCredentials) -> dict[str, str]:
    headers = dict(CODEX_CLIENT_HEADERS)
    account_id = credentials.account_id or _chatgpt_account_id(credentials.access_token)
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    return headers


def _login_codex(*_args: Any, **_kwargs: Any) -> None:
    # Backwards-compatible hook for older tests/integrations. The Responses provider reads the
    # existing Codex auth store and no longer opens an app-server login flow during generation.
    webbrowser.open("https://auth.openai.com/codex/device")
