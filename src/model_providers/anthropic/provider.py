from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import requests

from app_config.ai_settings import resolve_anthropic_api_key, resolve_anthropic_model
from model_providers.errors import ModelProviderAPIError, ModelProviderConfigError
from model_providers.types import ModelRequest, ModelResponse, ModelStreamEventSink, TokenUsage, ToolCall


DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 12800


class AnthropicModelProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_model: str | None = None,
        base_url: str | None = None,
        session: Any | None = None,
    ) -> None:
        self.default_model = default_model or resolve_anthropic_model().value or "claude-sonnet-4-6"
        self.base_url = (base_url or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
        self._session = session or requests.Session()
        self.api_key = api_key or resolve_anthropic_api_key().value
        if not self.api_key:
            raise ModelProviderConfigError("ANTHROPIC_API_KEY is required for AnthropicModelProvider.")

    def generate(self, request: ModelRequest) -> ModelResponse:
        model = request.model or self.default_model
        if not model:
            raise ModelProviderConfigError("A model is required for AnthropicModelProvider.")

        payload = build_anthropic_payload(request, model=model)
        response = self._session.post(
            f"{self.base_url}/messages",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "anthropic-version": ANTHROPIC_VERSION,
                "x-api-key": self.api_key,
            },
            timeout=request.request_options.get("timeout") or 600,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise _api_error_from_response(response)
        try:
            data = response.json()
        except ValueError as error:
            raise ModelProviderAPIError(
                f"Invalid JSON from Anthropic API: {error}",
                status_code=response.status_code,
                provider_data={"provider": "anthropic"},
            ) from error
        return normalize_anthropic_response(data, model=model)

    def stream_generate(
        self,
        request: ModelRequest,
        event_sink: ModelStreamEventSink | None = None,
    ) -> ModelResponse:
        return self.generate(request)


def build_anthropic_payload(request: ModelRequest, *, model: str) -> dict[str, Any]:
    messages, system_text = _build_anthropic_messages(request)
    thinking = _normalize_thinking(request.request_options.get("thinking"))
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": int(request.max_output_tokens or request.request_options.get("max_tokens") or DEFAULT_MAX_TOKENS),
        "messages": messages or [{"role": "user", "content": [{"type": "text", "text": ""}]}],
    }
    if thinking:
        payload["thinking"] = thinking
    output_config = _normalize_output_config(request.request_options.get("output_config") or request.request_options.get("outputConfig"))
    if output_config:
        payload["output_config"] = output_config
    if system_text:
        payload["system"] = system_text
    tools = _translate_tools_to_anthropic(request.tools)
    if _provider_native_web_search_enabled(request.request_options):
        tools.append({"type": "web_search_20260209", "name": "web_search"})
    if tools:
        payload["tools"] = tools
    for source_key, target_key in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("topP", "top_p"),
    ):
        if target_key == "temperature" and _thinking_is_enabled(thinking):
            continue
        if source_key in request.request_options:
            payload[target_key] = request.request_options[source_key]
    return payload


def _build_anthropic_messages(request: ModelRequest) -> tuple[list[dict[str, Any]], str]:
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []
    replay_thinking = _thinking_is_enabled(_normalize_thinking(request.request_options.get("thinking")))

    if request.instructions:
        system_parts.append(str(request.instructions))

    for message in request.messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role in {"system", "developer"}:
            system_parts.append(_content_to_text(message.get("content")))
            continue
        if role in {"tool", "function"}:
            messages.append({"role": "user", "content": [_translate_tool_result_to_anthropic(message)]})
            continue

        content = _extract_content_parts(message.get("content"))
        if role == "assistant" and replay_thinking:
            content = _anthropic_replay_blocks(message) + content
        tool_calls = message.get("tool_calls") or []
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                normalized = _tool_call_to_dict(tool_call)
                if normalized:
                    content.append(_translate_tool_call_to_anthropic(normalized))
        if content:
            messages.append({"role": "assistant" if role == "assistant" else "user", "content": content})

    return messages, "\n".join(part for part in system_parts if part).strip()


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
            elif isinstance(part, dict) and part.get("type") in {"text", "input_text", "output_text"}:
                text = part.get("text")
                if isinstance(text, str):
                    pieces.append(text)
        return "\n".join(pieces)
    return str(content)


def _extract_content_parts(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        text = _content_to_text(content)
        return [{"type": "text", "text": text}] if text else []

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            parts.append({"type": "text", "text": item})
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"text", "input_text", "output_text"}:
            text = item.get("text")
            if isinstance(text, str) and text:
                parts.append({"type": "text", "text": text})
            continue
        if item_type in {"image_url", "input_image"}:
            image = _translate_image_part_to_anthropic(item)
            if image:
                parts.append(image)
    return parts


def _anthropic_replay_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    provider_data = message.get("provider_data")
    if not isinstance(provider_data, dict):
        return []
    raw_blocks = provider_data.get("anthropic_thinking_blocks")
    if not isinstance(raw_blocks, list):
        return []
    blocks: list[dict[str, Any]] = []
    for block in raw_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "thinking":
            signature = block.get("signature")
            thinking_text = block.get("thinking")
            if isinstance(signature, str) and signature:
                blocks.append({
                    "type": "thinking",
                    "thinking": thinking_text if isinstance(thinking_text, str) else "",
                    "signature": signature,
                })
        elif block_type == "redacted_thinking":
            data = block.get("data")
            if isinstance(data, str):
                blocks.append({"type": "redacted_thinking", "data": data})
    return blocks


def _normalize_thinking(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    thinking_type = str(value.get("type") or "").strip().lower()
    if thinking_type not in {"adaptive", "enabled", "disabled"}:
        return None
    normalized: dict[str, Any] = {"type": thinking_type}
    display = str(value.get("display") or "").strip().lower()
    if display in {"summarized", "omitted"} and thinking_type != "disabled":
        normalized["display"] = display
    budget = value.get("budget_tokens", value.get("budgetTokens"))
    if thinking_type == "enabled" and budget is not None:
        try:
            normalized["budget_tokens"] = int(budget)
        except (TypeError, ValueError):
            pass
    return normalized


def _normalize_output_config(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, Any] = {}
    effort = str(value.get("effort") or "").strip().lower()
    if effort in {"low", "medium", "high", "xhigh", "max"}:
        normalized["effort"] = effort
    return normalized or None


def _thinking_is_enabled(thinking: dict[str, Any] | None) -> bool:
    return isinstance(thinking, dict) and thinking.get("type") in {"adaptive", "enabled"}


def _provider_native_web_search_enabled(request_options: dict[str, Any] | None) -> bool:
    if not isinstance(request_options, dict):
        return False
    value = request_options.get("_paper_notes_native_web_search", request_options.get("_paper_notes_provider_native_web_search"))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _translate_image_part_to_anthropic(item: dict[str, Any]) -> dict[str, Any] | None:
    url = item.get("image_url", {}).get("url") if isinstance(item.get("image_url"), dict) else item.get("image_url")
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("data:"):
        try:
            header, encoded = url.split(",", 1)
            media_type = header.split(":", 1)[1].split(";", 1)[0]
            raw = base64.b64decode(encoded)
        except Exception:
            return None
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(raw).decode("ascii"),
            },
        }
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _translate_tools_to_anthropic(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    translated: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") or {}
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        item: dict[str, Any] = {
            "name": name,
            "input_schema": function.get("parameters") if isinstance(function.get("parameters"), dict) else {"type": "object"},
        }
        description = function.get("description")
        if isinstance(description, str) and description:
            item["description"] = description
        translated.append(item)
    return translated


def _tool_call_to_dict(tool_call: Any) -> dict[str, Any]:
    if isinstance(tool_call, dict):
        return tool_call
    function = getattr(tool_call, "function", None)
    return {
        "id": getattr(tool_call, "id", None) or getattr(tool_call, "call_id", None),
        "function": {
            "name": getattr(function, "name", None) or getattr(tool_call, "name", ""),
            "arguments": getattr(function, "arguments", None) or getattr(tool_call, "arguments", "{}"),
        },
    }


def _translate_tool_call_to_anthropic(tool_call: dict[str, Any]) -> dict[str, Any]:
    function = tool_call.get("function") or {}
    raw_args = function.get("arguments") or tool_call.get("arguments") or "{}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else {}
    except json.JSONDecodeError:
        args = {"_raw": raw_args}
    if not isinstance(args, dict):
        args = {"_value": args}
    return {
        "type": "tool_use",
        "id": str(tool_call.get("id") or tool_call.get("call_id") or f"toolu_{uuid.uuid4().hex[:12]}"),
        "name": str(function.get("name") or tool_call.get("name") or ""),
        "input": args,
    }


def _translate_tool_result_to_anthropic(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": str(message.get("tool_call_id") or message.get("call_id") or ""),
        "content": _content_to_text(message.get("content")),
    }


def normalize_anthropic_response(data: dict[str, Any], *, model: str) -> ModelResponse:
    content = data.get("content") if isinstance(data, dict) else []
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    thinking_blocks: list[dict[str, Any]] = []
    work_trace_items: list[dict[str, Any]] = []
    web_search_calls: list[dict[str, Any]] = []
    web_search_sources: list[dict[str, str]] = []
    web_search_citations: list[dict[str, Any]] = []
    seen_web_search_urls: set[str] = set()
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
                _collect_anthropic_text_citations(
                    part,
                    citations=web_search_citations,
                    sources=web_search_sources,
                    seen_urls=seen_web_search_urls,
                )
            elif part.get("type") == "thinking":
                replay_block = {
                    "type": "thinking",
                    "thinking": part.get("thinking") if isinstance(part.get("thinking"), str) else "",
                    "signature": part.get("signature") if isinstance(part.get("signature"), str) else "",
                }
                if replay_block["signature"]:
                    thinking_blocks.append(replay_block)
                thinking_text = replay_block["thinking"].strip()
                if thinking_text:
                    work_trace_items.append({"type": "summary", "text": thinking_text, "source": "provider"})
            elif part.get("type") == "redacted_thinking":
                data_value = part.get("data")
                if isinstance(data_value, str) and data_value:
                    thinking_blocks.append({"type": "redacted_thinking", "data": data_value})
            elif part.get("type") == "tool_use" and part.get("name"):
                tool_calls.append(ToolCall(
                    id=str(part.get("id") or f"toolu_{uuid.uuid4().hex[:12]}"),
                    name=str(part["name"]),
                    arguments=json.dumps(part.get("input") or {}, ensure_ascii=False),
                ))
            elif part.get("type") == "server_tool_use":
                web_search_calls.append({
                    "id": part.get("id"),
                    "name": part.get("name"),
                    "input": part.get("input"),
                })
            elif part.get("type") == "web_search_tool_result":
                _collect_anthropic_web_search_result(
                    part,
                    sources=web_search_sources,
                    seen_urls=seen_web_search_urls,
                )

    usage_data = data.get("usage") if isinstance(data, dict) else {}
    input_tokens = int((usage_data or {}).get("input_tokens") or 0)
    output_tokens = int((usage_data or {}).get("output_tokens") or 0)
    usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )
    provider_data = {"provider": "anthropic", "model": model, "raw": data}
    if thinking_blocks:
        provider_data["anthropic_thinking_blocks"] = thinking_blocks
    if work_trace_items:
        provider_data["work_trace_items"] = work_trace_items
    if web_search_calls:
        provider_data["web_search_calls"] = web_search_calls
    if web_search_sources:
        provider_data["web_search_sources"] = web_search_sources
    if web_search_citations:
        provider_data["web_search_citations"] = web_search_citations
    return ModelResponse(
        content="".join(text_parts) if text_parts else None,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else _map_finish_reason(str(data.get("stop_reason") or "")),
        usage=usage,
        provider_data=provider_data,
    )


def _collect_anthropic_text_citations(
    part: dict[str, Any],
    *,
    citations: list[dict[str, Any]],
    sources: list[dict[str, str]],
    seen_urls: set[str],
) -> None:
    raw_citations = part.get("citations")
    if not isinstance(raw_citations, list):
        return
    for citation in raw_citations:
        if not isinstance(citation, dict):
            continue
        url = str(citation.get("url") or "")
        if not url:
            continue
        title = str(citation.get("title") or citation.get("cited_text") or "")
        snippet = str(citation.get("cited_text") or "")
        citations.append({
            "url": url,
            "title": title,
            "snippet": snippet,
            "start_index": citation.get("start_index"),
            "end_index": citation.get("end_index"),
        })
        if url not in seen_urls:
            seen_urls.add(url)
            sources.append({"url": url, "title": title, "snippet": snippet})


def _collect_anthropic_web_search_result(
    part: dict[str, Any],
    *,
    sources: list[dict[str, str]],
    seen_urls: set[str],
) -> None:
    content = part.get("content")
    items = content if isinstance(content, list) else [content]
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append({
            "url": url,
            "title": str(item.get("title") or ""),
            "snippet": str(item.get("page_age") or item.get("encrypted_content") or ""),
        })


def _map_finish_reason(reason: str) -> str:
    return {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
    }.get(reason, "stop")


def _api_error_from_response(response: Any) -> ModelProviderAPIError:
    message = ""
    body: dict[str, Any] = {}
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = body.get("error") if isinstance(body, dict) else {}
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("type") or "")
    if not message:
        message = str(getattr(response, "text", "") or "")[:500]
    return ModelProviderAPIError(
        f"Anthropic HTTP {response.status_code}: {message}",
        status_code=response.status_code,
        body=body or getattr(response, "text", ""),
        provider_data={"provider": "anthropic"},
    )
