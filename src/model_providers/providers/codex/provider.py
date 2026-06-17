"""说明：实现 Codex 作为模型 provider 的适配层。

作用：把 Paper Notes 的请求转换成 Codex Responses API 调用并返回统一结果。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from openai import OpenAI
from pydantic import Field

from model_providers.core.types import ModelProviderConfig
from model_providers.providers.codex.auth import (
    DEFAULT_CODEX_BASE_URL,
    codex_default_headers as _codex_default_headers,
    runtime_codex_credentials as _runtime_codex_credentials,
)
from model_providers.providers.codex.responses import (
    backfill_stream_output,
    codex_tool_spec,
    create_responses_response,
    final_generation_chunk_from_response,
    get_attr,
    message_from_responses_response,
    responses_payload,
    stream_chunk_from_responses_event,
    tool_call_chunks_from_tool_calls,
)

__all__ = [
    "CodexChatModel",
    "create_codex_chat_model",
]

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
            "bound_tools": [codex_tool_spec(tool) for tool in tools],
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
        response = create_responses_response(
            _codex_openai_client(options, explicit_client=self.client),
            responses_payload(messages, model=self.model, options=options, tools=self.bound_tools, tool_choice=self.tool_choice),
        )
        message = message_from_responses_response(response, options=options, model=self.model)
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
        payload = responses_payload(messages, model=self.model, options=options, tools=self.bound_tools, tool_choice=self.tool_choice)
        stream_factory = getattr(getattr(client, "responses", None), "stream", None)
        if not callable(stream_factory):
            result = self._generate(messages, **kwargs)
            message = result.generations[0].message
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=str(message.content or ""),
                    tool_call_chunks=tool_call_chunks_from_tool_calls(message.tool_calls),
                    chunk_position="last",
                    response_metadata=dict(message.response_metadata or {}),
                ),
                generation_info=result.generations[0].generation_info,
            )
            return

        streamed_content = False
        final_response: Any | None = None
        terminal_response: Any | None = None
        collected_output_items: list[Any] = []
        collected_text_deltas: list[str] = []
        with stream_factory(**payload) as stream:
            for event in stream:
                event_type = str(get_attr(event, "type", "") or "")
                if event_type in {"response.output_item.done", "response.output_item.completed"}:
                    item = get_attr(event, "item", None)
                    if item is not None:
                        collected_output_items.append(item)
                        collected_text_deltas.clear()
                elif event_type in {"response.output_text.delta", "response.text.delta"}:
                    delta = str(get_attr(event, "delta", "") or "")
                    if delta and not collected_output_items and not get_attr(terminal_response, "output", None):
                        collected_text_deltas.append(delta)
                elif event_type in {"response.completed", "response.incomplete", "response.failed"}:
                    terminal_response = get_attr(event, "response", None) or terminal_response
                    if get_attr(terminal_response, "output", None):
                        collected_text_deltas.clear()
                for chunk in stream_chunk_from_responses_event(event):
                    if str(chunk.message.content or ""):
                        streamed_content = True
                    yield chunk
            get_final_response = getattr(stream, "get_final_response", None)
            if callable(get_final_response):
                final_response = get_final_response()
        final_response = backfill_stream_output(
            final_response or terminal_response,
            collected_output_items=collected_output_items,
            collected_text_deltas=collected_text_deltas,
        )
        if final_response is None:
            raise RuntimeError("Codex Responses stream completed without a final response.")
        yield final_generation_chunk_from_response(final_response, suppress_content=streamed_content, options=options, model=self.model)


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
