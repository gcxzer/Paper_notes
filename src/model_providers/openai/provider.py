from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app_config.ai_settings import resolve_openai_api_key, resolve_openai_model
from media.image import ImageValidationError, shrink_image_data_url
from model_providers.errors import ModelProviderAPIError, ModelProviderConfigError
from model_providers.responses_adapter import (
    CODEX_PROVIDER_NAME,
    build_responses_payload,
    normalize_responses_response,
)
from model_providers.types import ModelRequest, ModelResponse, ModelStreamEvent, ModelStreamEventSink


class OpenAIModelProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_model: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.default_model = default_model or resolve_openai_model().value
        self._client = client
        if self._client is not None:
            return

        resolved_api_key = api_key or resolve_openai_api_key().value
        if not resolved_api_key:
            raise ModelProviderConfigError("OPENAI_API_KEY is required for OpenAIModelProvider.")

        from openai import OpenAI

        self._client = OpenAI(api_key=resolved_api_key)

    def generate(self, request: ModelRequest) -> ModelResponse:
        return self._generate(request, stream=False)

    def stream_generate(
        self,
        request: ModelRequest,
        event_sink: ModelStreamEventSink | None = None,
    ) -> ModelResponse:
        return self._generate(request, stream=True, event_sink=event_sink)

    def _generate(
        self,
        request: ModelRequest,
        *,
        stream: bool,
        event_sink: ModelStreamEventSink | None = None,
    ) -> ModelResponse:
        model = request.model or self.default_model
        if not model:
            raise ModelProviderConfigError("A model is required for OpenAIModelProvider.")

        provider_name = str(request.request_options.get("_paper_notes_provider") or self.name)
        payload = build_responses_payload(
            request,
            model=model,
            provider_name=provider_name,
            codex_strict=provider_name == CODEX_PROVIDER_NAME,
        )
        use_stream = stream or provider_name == CODEX_PROVIDER_NAME
        try:
            response = (
                _create_streaming_response(self._client, payload, event_sink=event_sink if stream else None)
                if use_stream
                else self._client.responses.create(**payload)
            )
        except Exception as error:
            if _should_retry_without_reasoning_summary(error, payload):
                retry_payload = _payload_without_reasoning_summary(payload)
                try:
                    response = (
                        _create_streaming_response(self._client, retry_payload, event_sink=event_sink if stream else None)
                        if use_stream
                        else self._client.responses.create(**retry_payload)
                    )
                except Exception as retry_error:
                    raise _api_error_from_exception(
                        retry_error,
                        provider_name=provider_name,
                        provider_native_web_search=_payload_has_web_search(payload),
                        provider_image_generation=_payload_has_image_generation(payload),
                    ) from retry_error
                return normalize_responses_response(
                    response,
                    request=request,
                    model=model,
                    provider_name=provider_name,
                )
            if _should_retry_with_shrunken_images(error, payload):
                retry_payload = _payload_with_shrunken_images(
                    payload,
                    target_bytes=int(
                        request.request_options.get("_paper_notes_image_retry_target_bytes") or 5 * 1024 * 1024
                    ),
                )
                if retry_payload is not None:
                    try:
                        response = (
                            _create_streaming_response(
                                self._client,
                                retry_payload,
                                event_sink=event_sink if stream else None,
                            )
                            if use_stream
                            else self._client.responses.create(**retry_payload)
                        )
                    except Exception as retry_error:
                        raise _api_error_from_exception(
                            retry_error,
                            provider_name=provider_name,
                            provider_native_web_search=_payload_has_web_search(payload),
                            provider_image_generation=_payload_has_image_generation(payload),
                        ) from retry_error
                    return normalize_responses_response(
                        response,
                        request=request,
                        model=model,
                        provider_name=provider_name,
                    )
            raise _api_error_from_exception(
                error,
                provider_name=provider_name,
                provider_native_web_search=_payload_has_web_search(payload),
                provider_image_generation=_payload_has_image_generation(payload),
            ) from error

        return normalize_responses_response(response, request=request, model=model, provider_name=provider_name)


def _create_streaming_response(
    client: Any,
    payload: dict[str, Any],
    *,
    event_sink: ModelStreamEventSink | None = None,
) -> Any:
    """Call Responses with stream=True and return the final response.

    The ChatGPT Codex backend requires streaming even when the app itself does
    not expose token streaming yet. This helper keeps the runtime synchronous by
    collecting the terminal response. When an event sink is supplied, text
    deltas are also emitted for SSE/UI consumers.
    """
    stream_payload = {**payload, "stream": True}
    stream_or_response = client.responses.create(**stream_payload)
    if hasattr(stream_or_response, "output"):
        return stream_or_response

    if hasattr(stream_or_response, "__enter__"):
        with stream_or_response as stream:
            return _collect_stream_response(stream, event_sink=event_sink)
    return _collect_stream_response(stream_or_response, event_sink=event_sink)


def _collect_stream_response(stream: Any, *, event_sink: ModelStreamEventSink | None = None) -> Any:
    terminal_response = None
    collected_output_items: list[Any] = []
    collected_text_deltas: list[str] = []
    collected_reasoning_deltas: list[str] = []

    for event in stream:
        event_type = _event_value(event, "type")
        if event_type == "response.output_item.done":
            item = _event_value(event, "item")
            if item is not None:
                collected_output_items.append(item)
                _emit_output_item_work_trace(event_sink, item)
        elif event_type == "response.output_text.delta":
            delta = _event_value(event, "delta") or ""
            if delta:
                delta_text = str(delta)
                collected_text_deltas.append(delta_text)
                _emit_stream_event(
                    event_sink,
                    ModelStreamEvent(
                        type="text_delta",
                        delta=delta_text,
                        text="".join(collected_text_deltas),
                        data={"response_event_type": event_type},
                    ),
                )
        elif _is_reasoning_summary_delta_event(event_type):
            delta = _event_value(event, "delta") or _event_value(event, "text") or ""
            if delta:
                delta_text = str(delta)
                collected_reasoning_deltas.append(delta_text)
                _emit_stream_event(
                    event_sink,
                    ModelStreamEvent(
                        type="reasoning_summary_delta",
                        delta=delta_text,
                        text="".join(collected_reasoning_deltas),
                        data={"response_event_type": event_type},
                    ),
                )
        elif _is_reasoning_summary_done_event(event_type):
            text = _event_value(event, "text") or _event_value(event, "summary") or "".join(collected_reasoning_deltas)
            if text:
                _emit_stream_event(
                    event_sink,
                    ModelStreamEvent(
                        type="reasoning_summary_done",
                        text=str(text),
                        data={"response_event_type": event_type},
                    ),
                )
                collected_reasoning_deltas = []
        elif event_type in {"response.completed", "response.incomplete", "response.failed"}:
            terminal_response = _event_value(event, "response") or terminal_response

    final_response = terminal_response
    get_final_response = getattr(stream, "get_final_response", None)
    if callable(get_final_response):
        try:
            final_response = get_final_response() or final_response
        except RuntimeError:
            pass

    if final_response is None:
        final_response = SimpleNamespace(id="", status="completed", output=[], output_text="", usage=None)

    return _backfill_codex_stream_output(
        final_response,
        collected_output_items=collected_output_items,
        collected_text_deltas=collected_text_deltas,
    )


def _emit_stream_event(event_sink: ModelStreamEventSink | None, event: ModelStreamEvent) -> None:
    if event_sink is None:
        return
    event_sink(event)


def _is_reasoning_summary_delta_event(event_type: Any) -> bool:
    text = str(event_type or "")
    return "reasoning" in text and "summary" in text and text.endswith(".delta")


def _is_reasoning_summary_done_event(event_type: Any) -> bool:
    text = str(event_type or "")
    return "reasoning" in text and "summary" in text and (text.endswith(".done") or text.endswith(".completed"))


def _emit_output_item_work_trace(event_sink: ModelStreamEventSink | None, item: Any) -> None:
    item_type = str(_value(item, "type") or "")
    if item_type == "reasoning":
        for text in _reasoning_summary_texts(item):
            _emit_stream_event(
                event_sink,
                ModelStreamEvent(
                    type="reasoning_summary_done",
                    text=text,
                    data={"response_event_type": "response.output_item.done"},
                ),
            )
        return
    if item_type != "message":
        return
    phase = str(_value(item, "phase") or "").strip()
    if phase not in {"commentary", "analysis"}:
        return
    text = _message_text(item)
    if not text:
        return
    _emit_stream_event(
        event_sink,
        ModelStreamEvent(
            type="assistant_commentary_done",
            text=text,
            data={"response_event_type": "response.output_item.done", "phase": phase},
        ),
    )


def _reasoning_summary_texts(item: Any) -> list[str]:
    summary = _value(item, "summary")
    if not isinstance(summary, list):
        return []
    texts: list[str] = []
    for part in summary:
        text = _value(part, "text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    return texts


def _message_text(item: Any) -> str:
    content = _value(item, "content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        text = _value(part, "text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def _value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _backfill_codex_stream_output(
    response: Any,
    *,
    collected_output_items: list[Any],
    collected_text_deltas: list[str],
) -> Any:
    output = getattr(response, "output", None)
    if isinstance(output, list) and output:
        return response
    if collected_output_items:
        try:
            response.output = list(collected_output_items)
        except Exception:
            pass
        return response
    if collected_text_deltas:
        text = "".join(collected_text_deltas)
        try:
            response.output = [
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[SimpleNamespace(type="output_text", text=text)],
                )
            ]
            response.output_text = getattr(response, "output_text", None) or text
        except Exception:
            return SimpleNamespace(id="", status="completed", output_text=text, output=[], usage=None)
    return response


def _event_value(event: Any, key: str) -> Any:
    if isinstance(event, dict):
        return event.get(key)
    return getattr(event, key, None)


def _should_retry_with_shrunken_images(error: Exception, payload: dict[str, Any]) -> bool:
    if not _payload_has_data_url_images(payload):
        return False
    text = _error_text(error).lower()
    return any(
        phrase in text
        for phrase in (
            "image exceeds",
            "image too large",
            "image size",
            "payload too large",
            "maximum image",
            "request entity too large",
            "413",
        )
    )


def _should_retry_without_reasoning_summary(error: Exception, payload: dict[str, Any]) -> bool:
    reasoning = payload.get("reasoning")
    if not isinstance(reasoning, dict) or not reasoning.get("summary"):
        return False
    text = _error_text(error).lower()
    return "reasoning" in text and any(
        phrase in text
        for phrase in (
            "unsupported",
            "unknown parameter",
            "invalid parameter",
            "not supported",
            "not available",
            "organization verification",
            "verified organization",
        )
    )


def _payload_without_reasoning_summary(payload: dict[str, Any]) -> dict[str, Any]:
    retry_payload = dict(payload)
    reasoning = retry_payload.get("reasoning")
    if isinstance(reasoning, dict):
        next_reasoning = dict(reasoning)
        next_reasoning.pop("summary", None)
        if next_reasoning:
            retry_payload["reasoning"] = next_reasoning
        else:
            retry_payload.pop("reasoning", None)
    include = retry_payload.get("include")
    if isinstance(include, list):
        retry_payload["include"] = [item for item in include if item != "reasoning.encrypted_content"]
        if not retry_payload["include"]:
            retry_payload.pop("include", None)
    return retry_payload


def _payload_has_data_url_images(payload: dict[str, Any]) -> bool:
    for part in _iter_payload_content_parts(payload):
        if isinstance(part, dict) and str(part.get("type") or "") == "input_image":
            image_url = part.get("image_url")
            if isinstance(image_url, str) and image_url.startswith("data:image/"):
                return True
    return False


def _payload_has_web_search(payload: dict[str, Any]) -> bool:
    tools = payload.get("tools")
    return isinstance(tools, list) and any(
        isinstance(tool, dict) and tool.get("type") == "web_search"
        for tool in tools
    )


def _payload_has_image_generation(payload: dict[str, Any]) -> bool:
    tools = payload.get("tools")
    return isinstance(tools, list) and any(
        isinstance(tool, dict) and tool.get("type") == "image_generation"
        for tool in tools
    )


def _payload_with_shrunken_images(payload: dict[str, Any], *, target_bytes: int) -> dict[str, Any] | None:
    changed = False
    next_payload = dict(payload)
    next_input = []
    for item in payload.get("input", []) if isinstance(payload.get("input"), list) else []:
        if not isinstance(item, dict):
            next_input.append(item)
            continue
        next_item = dict(item)
        content = item.get("content")
        if isinstance(content, list):
            next_content = []
            for part in content:
                if not isinstance(part, dict) or str(part.get("type") or "") != "input_image":
                    next_content.append(part)
                    continue
                image_url = part.get("image_url")
                if not isinstance(image_url, str) or not image_url.startswith("data:image/"):
                    next_content.append(part)
                    continue
                try:
                    shrunk = shrink_image_data_url(image_url, target_bytes=target_bytes)
                except (ImageValidationError, ValueError):
                    next_content.append(part)
                    continue
                next_part = dict(part)
                next_part["image_url"] = shrunk
                changed = changed or shrunk != image_url
                next_content.append(next_part)
            next_item["content"] = next_content
        next_input.append(next_item)
    if not changed:
        return None
    next_payload["input"] = next_input
    return next_payload


def _iter_payload_content_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for item in payload.get("input", []) if isinstance(payload.get("input"), list) else []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, list):
            parts.extend(part for part in content if isinstance(part, dict))
    return parts


def _error_text(error: Exception) -> str:
    response = getattr(error, "response", None)
    body = getattr(error, "body", None)
    return " ".join(
        str(value)
        for value in (
            error,
            body,
            getattr(response, "text", None),
            getattr(response, "content", None),
            getattr(error, "status_code", None),
            getattr(response, "status_code", None),
        )
        if value is not None
    )


def _api_error_from_exception(
    error: Exception,
    *,
    provider_name: str,
    provider_native_web_search: bool = False,
    provider_image_generation: bool = False,
) -> ModelProviderAPIError:
    response = getattr(error, "response", None)
    status_code = getattr(error, "status_code", None) or getattr(response, "status_code", None)
    body = getattr(error, "body", None)
    if body is None:
        body = getattr(response, "text", None) or getattr(response, "content", None)
    message = str(error) or "OpenAI Responses API request failed."
    code = ""
    api_error = _openai_error_details(body)
    if provider_native_web_search:
        text = _error_text(error).lower()
        if provider_name == CODEX_PROVIDER_NAME and any(token in text for token in ("web_search", "web search", "unsupported")):
            code = "native_web_search_unavailable"
            message = (
                "Native Web Search was rejected by the Codex Responses backend. "
                "Disable Native Web Search or use Tavily Web Search instead."
            )
    if provider_image_generation:
        code = "image_generation_unavailable"
        if provider_name == CODEX_PROVIDER_NAME:
            message = (
                "Image generation is not available through Codex OAuth in Paper Notes. "
                "Switch to the OpenAI API key provider to generate images."
            )
        else:
            message = (
                "Image generation was rejected by the selected provider or model. "
                "Switch to a model that supports the Responses image_generation tool."
            )
    return ModelProviderAPIError(
        message,
        status_code=int(status_code) if status_code else None,
        body=body,
        provider_data={
            "provider": provider_name,
            **({"code": code} if code else {}),
            **({"api_error_code": api_error["code"]} if api_error.get("code") else {}),
            **({"api_error_type": api_error["type"]} if api_error.get("type") else {}),
            **({"api_error_param": api_error["param"]} if api_error.get("param") else {}),
        },
    )


def _openai_error_details(body: object) -> dict[str, str]:
    if not isinstance(body, dict):
        return {}
    raw = body.get("error")
    if isinstance(raw, dict):
        error_body = raw
    else:
        error_body = body
    details: dict[str, str] = {}
    for key in ("code", "type", "param"):
        value = error_body.get(key)
        if value not in (None, "", [], {}):
            details[key] = str(value)
    return details
