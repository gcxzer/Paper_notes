from __future__ import annotations

import json
import uuid
from typing import Any

import requests

from app_config.ai_settings import resolve_deepseek_api_key, resolve_deepseek_model
from model_providers.errors import ModelProviderAPIError, ModelProviderConfigError
from model_providers.types import ModelRequest, ModelResponse, ModelStreamEventSink, TokenUsage, ToolCall


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MAX_TOKENS = 12800


class DeepSeekModelProvider:
    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_model: str | None = None,
        base_url: str | None = None,
        session: Any | None = None,
    ) -> None:
        self.default_model = default_model or resolve_deepseek_model().value or "deepseek-v4-flash"
        self.base_url = (base_url or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")
        self._session = session or requests.Session()
        self.api_key = api_key or resolve_deepseek_api_key().value
        if not self.api_key:
            raise ModelProviderConfigError("DEEPSEEK_API_KEY is required for DeepSeekModelProvider.")

    def generate(self, request: ModelRequest) -> ModelResponse:
        model = request.model or self.default_model
        if not model:
            raise ModelProviderConfigError("A model is required for DeepSeekModelProvider.")

        payload = build_deepseek_payload(request, model=model)
        response = self._session.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=request.request_options.get("timeout") or 600,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise _api_error_from_response(response)
        try:
            data = response.json()
        except ValueError as error:
            raise ModelProviderAPIError(
                f"Invalid JSON from DeepSeek API: {error}",
                status_code=response.status_code,
                provider_data={"provider": "deepseek"},
            ) from error
        return normalize_deepseek_response(data, model=model)

    def stream_generate(
        self,
        request: ModelRequest,
        event_sink: ModelStreamEventSink | None = None,
    ) -> ModelResponse:
        return self.generate(request)


def build_deepseek_payload(request: ModelRequest, *, model: str) -> dict[str, Any]:
    messages = _build_deepseek_messages(request)
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages or [{"role": "user", "content": ""}],
        "stream": False,
    }
    if request.max_output_tokens is not None:
        payload["max_tokens"] = request.max_output_tokens
    elif request.request_options.get("max_tokens"):
        payload["max_tokens"] = int(request.request_options["max_tokens"])
    else:
        payload["max_tokens"] = DEFAULT_MAX_TOKENS

    tools = _translate_tools_to_deepseek(request.tools)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    has_reasoning_effort = False
    for source_key, target_key in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("topP", "top_p"),
        ("reasoning_effort", "reasoning_effort"),
        ("reasoningEffort", "reasoning_effort"),
    ):
        if source_key in request.request_options:
            if target_key == "reasoning_effort":
                effort = _normalize_reasoning_effort(request.request_options[source_key])
                if effort:
                    payload[target_key] = effort
                    has_reasoning_effort = True
                continue
            payload[target_key] = request.request_options[source_key]

    thinking = request.request_options.get("thinking")
    if isinstance(thinking, dict):
        payload["thinking"] = thinking
    elif has_reasoning_effort:
        payload["thinking"] = {"type": "enabled"}
    return payload


def _build_deepseek_messages(request: ModelRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if request.instructions:
        messages.append({"role": "system", "content": str(request.instructions)})

    for message in request.messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role == "developer":
            role = "system"
        if role in {"system", "user"}:
            content = _content_to_text(message.get("content"))
            if content:
                messages.append({"role": role, "content": content})
            continue
        if role == "assistant":
            assistant_message: dict[str, Any] = {"role": "assistant", "content": _content_to_text(message.get("content"))}
            reasoning_content = _message_reasoning_content(message)
            if reasoning_content:
                assistant_message["reasoning_content"] = reasoning_content
            tool_calls = [_translate_tool_call_to_deepseek(call) for call in message.get("tool_calls") or []]
            tool_calls = [call for call in tool_calls if call]
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            if assistant_message["content"] or reasoning_content or tool_calls:
                messages.append(assistant_message)
            continue
        if role in {"tool", "function"}:
            messages.append({
                "role": "tool",
                "tool_call_id": str(message.get("tool_call_id") or message.get("call_id") or ""),
                "content": _content_to_text(message.get("content")),
            })
    return messages


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


def _message_reasoning_content(message: dict[str, Any]) -> str:
    direct = message.get("reasoning_content")
    if isinstance(direct, str) and direct:
        return direct
    provider_data = message.get("provider_data")
    if isinstance(provider_data, dict):
        nested = provider_data.get("reasoning_content")
        if isinstance(nested, str) and nested:
            return nested
    return ""


def _normalize_reasoning_effort(value: Any) -> str | None:
    effort = str(value or "").strip().lower()
    if effort == "high":
        return "high"
    if effort == "max":
        return "max"
    return None


def _translate_tools_to_deepseek(tools: Any) -> list[dict[str, Any]]:
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
        translated.append({
            "type": "function",
            "function": {
                "name": name,
                "description": function.get("description") or "",
                "parameters": function.get("parameters") if isinstance(function.get("parameters"), dict) else {"type": "object"},
            },
        })
    return translated


def _tool_call_to_dict(tool_call: Any) -> dict[str, Any]:
    if isinstance(tool_call, dict):
        return tool_call
    function = getattr(tool_call, "function", None)
    return {
        "id": getattr(tool_call, "id", None) or getattr(tool_call, "call_id", None),
        "type": "function",
        "function": {
            "name": getattr(function, "name", None) or getattr(tool_call, "name", ""),
            "arguments": getattr(function, "arguments", None) or getattr(tool_call, "arguments", "{}"),
        },
    }


def _translate_tool_call_to_deepseek(tool_call: Any) -> dict[str, Any]:
    normalized = _tool_call_to_dict(tool_call)
    function = normalized.get("function") or {}
    name = function.get("name") or normalized.get("name")
    if not name:
        return {}
    arguments = function.get("arguments") or normalized.get("arguments") or "{}"
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return {
        "id": str(normalized.get("id") or normalized.get("call_id") or f"call_{uuid.uuid4().hex[:12]}"),
        "type": "function",
        "function": {"name": str(name), "arguments": arguments},
    }


def normalize_deepseek_response(data: dict[str, Any], *, model: str) -> ModelResponse:
    choice = (data.get("choices") or [{}])[0] if isinstance(data, dict) else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    text = message.get("content") if isinstance(message, dict) else None
    reasoning_content = message.get("reasoning_content") if isinstance(message, dict) else None
    tool_calls: list[ToolCall] = []
    for tool_call in (message.get("tool_calls") or []) if isinstance(message, dict) else []:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function") or {}
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        tool_calls.append(ToolCall(
            id=str(tool_call.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
            name=name,
            arguments=str(function.get("arguments") or "{}"),
        ))

    usage_data = data.get("usage") if isinstance(data, dict) else {}
    usage = TokenUsage(
        input_tokens=int((usage_data or {}).get("prompt_tokens") or 0),
        output_tokens=int((usage_data or {}).get("completion_tokens") or 0),
        total_tokens=int((usage_data or {}).get("total_tokens") or 0),
    )
    provider_data = {"provider": "deepseek", "model": model, "raw": data}
    if isinstance(reasoning_content, str) and reasoning_content:
        provider_data["reasoning_content"] = reasoning_content

    return ModelResponse(
        content=text if isinstance(text, str) and text else None,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else _map_finish_reason(str(choice.get("finish_reason") or "")),
        usage=usage,
        provider_data=provider_data,
    )


def _map_finish_reason(reason: str) -> str:
    return {
        "stop": "stop",
        "length": "length",
        "content_filter": "content_filter",
        "tool_calls": "tool_calls",
        "insufficient_system_resource": "stop",
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
        f"DeepSeek HTTP {response.status_code}: {message}",
        status_code=response.status_code,
        body=body or getattr(response, "text", ""),
        provider_data={"provider": "deepseek"},
    )
