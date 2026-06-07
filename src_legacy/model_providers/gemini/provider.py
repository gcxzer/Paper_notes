from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import requests

from app_config.ai_settings import resolve_gemini_api_key, resolve_gemini_model
from model_providers.errors import ModelProviderAPIError, ModelProviderConfigError
from model_providers.gemini.schema import sanitize_gemini_tool_parameters
from model_providers.types import ModelRequest, ModelResponse, ModelStreamEventSink, TokenUsage, ToolCall


DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiModelProvider:
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_model: str | None = None,
        base_url: str | None = None,
        session: Any | None = None,
    ) -> None:
        self.default_model = default_model or resolve_gemini_model().value or "gemini-3-flash-preview"
        self.base_url = (base_url or DEFAULT_GEMINI_BASE_URL).rstrip("/")
        self._session = session or requests.Session()
        self.api_key = api_key or resolve_gemini_api_key().value
        if not self.api_key:
            raise ModelProviderConfigError("GEMINI_API_KEY or GOOGLE_API_KEY is required for GeminiModelProvider.")

    def generate(self, request: ModelRequest) -> ModelResponse:
        model = request.model or self.default_model
        if not model:
            raise ModelProviderConfigError("A model is required for GeminiModelProvider.")
        if not _is_supported_gemini_model(model):
            raise ModelProviderConfigError("GeminiModelProvider only supports Gemini 3 text models.")

        payload = build_gemini_payload(request, model=model)
        response = self._session.post(
            f"{self.base_url}/models/{model}:generateContent",
            params={"key": self.api_key},
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=request.request_options.get("timeout") or 600,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise _api_error_from_response(response)
        try:
            data = response.json()
        except ValueError as error:
            raise ModelProviderAPIError(
                f"Invalid JSON from Gemini API: {error}",
                status_code=response.status_code,
                provider_data={"provider": "gemini"},
            ) from error
        return normalize_gemini_response(data, model=model)

    def stream_generate(
        self,
        request: ModelRequest,
        event_sink: ModelStreamEventSink | None = None,
    ) -> ModelResponse:
        return self.generate(request)


def build_gemini_payload(request: ModelRequest, *, model: str) -> dict[str, Any]:
    contents, system_instruction = _build_gemini_contents(request)
    payload: dict[str, Any] = {"contents": contents or [{"role": "user", "parts": [{"text": ""}]}]}
    if system_instruction:
        payload["systemInstruction"] = system_instruction

    function_tools = _translate_tools_to_gemini(request.tools)
    tools = list(function_tools)
    if _provider_native_web_search_enabled(request.request_options):
        tools.append({"googleSearch": {}})
    if tools:
        payload["tools"] = tools
    if function_tools:
        payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

    generation_config: dict[str, Any] = {}
    if request.max_output_tokens is not None:
        generation_config["maxOutputTokens"] = request.max_output_tokens
    for source_key, target_key in (
        ("temperature", "temperature"),
        ("top_p", "topP"),
        ("topP", "topP"),
    ):
        if source_key in request.request_options:
            generation_config[target_key] = request.request_options[source_key]
    thinking_config = _normalize_thinking_config(
        request.request_options.get("thinking_config") or request.request_options.get("thinkingConfig")
    )
    if thinking_config:
        generation_config["thinkingConfig"] = thinking_config
    if generation_config:
        payload["generationConfig"] = generation_config
    return payload


def _build_gemini_contents(request: ModelRequest) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    system_text_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    tool_name_by_call_id: dict[str, str] = {}

    if request.instructions:
        system_text_parts.append(str(request.instructions))

    for message in request.messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role in {"system", "developer"}:
            system_text_parts.append(_content_to_text(message.get("content")))
            continue
        if role in {"tool", "function"}:
            contents.append({
                "role": "user",
                "parts": [_translate_tool_result_to_gemini(message, tool_name_by_call_id=tool_name_by_call_id)],
            })
            continue

        parts = _extract_content_parts(message.get("content"))
        tool_calls = message.get("tool_calls") or []
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                normalized = _tool_call_to_dict(tool_call)
                call_id = str(normalized.get("id") or normalized.get("call_id") or "")
                tool_name = str(((normalized.get("function") or {}).get("name") or normalized.get("name") or ""))
                if call_id and tool_name:
                    tool_name_by_call_id[call_id] = tool_name
                if normalized:
                    parts.append(_translate_tool_call_to_gemini(normalized))
        if parts:
            contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})

    system_text = "\n".join(part for part in system_text_parts if part).strip()
    system_instruction = {"parts": [{"text": system_text}]} if system_text else None
    return contents, system_instruction


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
        return [{"text": text}] if text else []

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            parts.append({"text": item})
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"text", "input_text", "output_text"}:
            text = item.get("text")
            if isinstance(text, str) and text:
                parts.append({"text": text})
            continue
        if item_type in {"image_url", "input_image"}:
            url = item.get("image_url", {}).get("url") if isinstance(item.get("image_url"), dict) else item.get("image_url")
            if not isinstance(url, str) or not url.startswith("data:"):
                continue
            try:
                header, encoded = url.split(",", 1)
                mime_type = header.split(":", 1)[1].split(";", 1)[0]
                raw = base64.b64decode(encoded)
            except Exception:
                continue
            parts.append({"inlineData": {"mimeType": mime_type, "data": base64.b64encode(raw).decode("ascii")}})
    return parts


def _translate_tools_to_gemini(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    declarations: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") or {}
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        declaration: dict[str, Any] = {"name": name}
        description = function.get("description")
        if isinstance(description, str) and description:
            declaration["description"] = description
        parameters = function.get("parameters")
        if isinstance(parameters, dict):
            declaration["parameters"] = sanitize_gemini_tool_parameters(parameters)
        declarations.append(declaration)
    return [{"functionDeclarations": declarations}] if declarations else []


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


def _translate_tool_call_to_gemini(tool_call: dict[str, Any]) -> dict[str, Any]:
    function = tool_call.get("function") or {}
    raw_args = function.get("arguments") or tool_call.get("arguments") or "{}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else {}
    except json.JSONDecodeError:
        args = {"_raw": raw_args}
    if not isinstance(args, dict):
        args = {"_value": args}
    part = {"functionCall": {"name": str(function.get("name") or tool_call.get("name") or ""), "args": args}}
    thought_signature = tool_call.get("thoughtSignature") or tool_call.get("thought_signature")
    if isinstance(thought_signature, str) and thought_signature:
        part["thoughtSignature"] = thought_signature
    return part


def _translate_tool_result_to_gemini(
    message: dict[str, Any],
    *,
    tool_name_by_call_id: dict[str, str],
) -> dict[str, Any]:
    tool_call_id = str(message.get("tool_call_id") or message.get("call_id") or "")
    name = str(message.get("name") or tool_name_by_call_id.get(tool_call_id) or tool_call_id or "tool")
    content = _content_to_text(message.get("content"))
    try:
        parsed = json.loads(content) if content.strip().startswith(("{", "[")) else None
    except json.JSONDecodeError:
        parsed = None
    return {"functionResponse": {"name": name, "response": parsed if isinstance(parsed, dict) else {"output": content}}}


def _normalize_thinking_config(config: Any) -> dict[str, Any] | None:
    if not isinstance(config, dict) or not config:
        return None
    normalized: dict[str, Any] = {}
    budget = config.get("thinkingBudget", config.get("thinking_budget"))
    include = config.get("includeThoughts", config.get("include_thoughts"))
    level = config.get("thinkingLevel", config.get("thinking_level"))
    if isinstance(budget, int | float):
        normalized["thinkingBudget"] = int(budget)
    if isinstance(level, str) and level.strip().lower() in {"minimal", "low", "medium", "high"}:
        normalized["thinkingLevel"] = level.strip().lower()
    if isinstance(include, bool):
        normalized["includeThoughts"] = include
    return normalized or None


def _provider_native_web_search_enabled(request_options: dict[str, Any] | None) -> bool:
    if not isinstance(request_options, dict):
        return False
    value = request_options.get("_paper_notes_native_web_search", request_options.get("_paper_notes_provider_native_web_search"))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def normalize_gemini_response(data: dict[str, Any], *, model: str) -> ModelResponse:
    candidate = (data.get("candidates") or [{}])[0]
    parts = ((candidate.get("content") or {}).get("parts") or []) if isinstance(candidate, dict) else []
    text_parts: list[str] = []
    thought_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            if part.get("thought"):
                thought_parts.append(text)
            else:
                text_parts.append(text)
            continue
        function_call = part.get("functionCall")
        if isinstance(function_call, dict) and function_call.get("name"):
            tool_calls.append(ToolCall(
                id=f"call_{uuid.uuid4().hex[:12]}",
                name=str(function_call["name"]),
                arguments=json.dumps(function_call.get("args") or {}, ensure_ascii=False),
                provider_data={
                    "thought_signature": part.get("thoughtSignature"),
                } if isinstance(part.get("thoughtSignature"), str) and part.get("thoughtSignature") else None,
            ))

    usage_meta = data.get("usageMetadata") if isinstance(data, dict) else {}
    usage = TokenUsage(
        input_tokens=int((usage_meta or {}).get("promptTokenCount") or 0),
        output_tokens=int((usage_meta or {}).get("candidatesTokenCount") or 0),
        total_tokens=int((usage_meta or {}).get("totalTokenCount") or 0),
    )
    provider_data = {
        "provider": "gemini",
        "model": model,
        "raw": data,
        "work_trace_items": [
            {"type": "summary", "text": text, "source": "provider"}
            for text in thought_parts
            if text.strip()
        ],
    }
    provider_data.update(_gemini_web_search_metadata(candidate))
    return ModelResponse(
        content="".join(text_parts) if text_parts else None,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else _map_finish_reason(str(candidate.get("finishReason") or "")),
        usage=usage,
        provider_data=provider_data,
    )


def _gemini_web_search_metadata(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    metadata = candidate.get("groundingMetadata") or candidate.get("grounding_metadata")
    if not isinstance(metadata, dict):
        return {}
    chunks = metadata.get("groundingChunks") or metadata.get("grounding_chunks") or []
    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    if isinstance(chunks, list):
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            web = chunk.get("web")
            if not isinstance(web, dict):
                continue
            source = {
                "title": str(web.get("title") or ""),
                "url": str(web.get("uri") or web.get("url") or ""),
                "snippet": "",
            }
            if source["url"] and source["url"] not in seen_urls:
                seen_urls.add(source["url"])
                sources.append(source)

    citations: list[dict[str, Any]] = []
    supports = metadata.get("groundingSupports") or metadata.get("grounding_supports") or []
    if isinstance(supports, list) and isinstance(chunks, list):
        for support in supports:
            if not isinstance(support, dict):
                continue
            segment = support.get("segment") if isinstance(support.get("segment"), dict) else {}
            indices = support.get("groundingChunkIndices") or support.get("grounding_chunk_indices") or []
            if not isinstance(indices, list):
                continue
            for index in indices:
                if not isinstance(index, int) or index < 0 or index >= len(chunks):
                    continue
                chunk = chunks[index]
                web = chunk.get("web") if isinstance(chunk, dict) else None
                if not isinstance(web, dict):
                    continue
                url = str(web.get("uri") or web.get("url") or "")
                if not url:
                    continue
                citations.append({
                    "url": url,
                    "title": str(web.get("title") or ""),
                    "snippet": str(segment.get("text") or ""),
                    "start_index": segment.get("startIndex", segment.get("start_index")),
                    "end_index": segment.get("endIndex", segment.get("end_index")),
                })

    calls = []
    queries = metadata.get("webSearchQueries") or metadata.get("web_search_queries")
    if isinstance(queries, list) and queries:
        calls.append({"queries": [str(query) for query in queries if str(query).strip()]})
    return {
        "web_search_calls": calls or None,
        "web_search_sources": sources or None,
        "web_search_citations": citations or None,
    }


def _is_supported_gemini_model(model: str) -> bool:
    return model in {"gemini-3-flash-preview", "gemini-3-pro-preview"}


def _map_finish_reason(reason: str) -> str:
    return {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
        "RECITATION": "content_filter",
        "OTHER": "stop",
    }.get(reason.upper(), "stop")


def _api_error_from_response(response: Any) -> ModelProviderAPIError:
    message = ""
    body: dict[str, Any] = {}
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = body.get("error") if isinstance(body, dict) else {}
    if isinstance(error, dict):
        message = str(error.get("message") or "")
    if not message:
        message = str(getattr(response, "text", "") or "")[:500]
    return ModelProviderAPIError(
        f"Gemini HTTP {response.status_code}: {message}",
        status_code=response.status_code,
        body=body or getattr(response, "text", ""),
        provider_data={"provider": "gemini"},
    )
