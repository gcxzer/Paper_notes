from __future__ import annotations

import copy
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from agent_runtime.messages import last_assistant_text, messages_from_final_chunk
from app_config import AppConfig


RECOVERY_MESSAGE_NAME = "paper_notes_recovery"
RECOVERABLE_REQUEST_OPTION_KEYS = {
    "_paper_notes_image_generation",
    "imageGeneration",
    "image_generation",
    "_paper_notes_native_web_search",
    "_paper_notes_provider_native_web_search",
    "native_web_search",
    "web_search",
    "temperature",
    "top_p",
    "reasoning",
    "reasoning_effort",
    "effort",
    "summary",
    "thinking",
    "thinking_level",
    "include_thoughts",
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
    "response_format",
    "tool_choice",
    "parallel_tool_calls",
}


def is_recoverable_model_request_error(error: Exception) -> bool:
    text = exception_text(error).lower()
    if not text:
        return False
    has_request_failure = any(
        marker in text
        for marker in (
            "invalid_request_error",
            "bad request",
            "error code: 400",
            "status code: 400",
            "unsupported",
            "not supported",
        )
    )
    if not has_request_failure:
        return False
    return any(
        marker in text
        for marker in (
            "tool",
            "tools",
            "parameter",
            "image_generation",
            "web_search",
            "temperature",
            "reasoning",
            "tool_choice",
            "response_format",
            "max_output_tokens",
        )
    )


def model_config_for_recovery(config: AppConfig) -> AppConfig:
    data = copy.deepcopy(config.data)
    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    default_key = str(models.get("default") or "main")
    section = dict(models.get(default_key) if isinstance(models.get(default_key), dict) else {})
    options = dict(section.get("options") if isinstance(section.get("options"), dict) else {})
    for key in RECOVERABLE_REQUEST_OPTION_KEYS:
        options.pop(key, None)
    section["options"] = options
    models[default_key] = section
    data["models"] = models
    return AppConfig(data=data, path=config.path)


def messages_with_recovery_instruction(
    input_messages: list[BaseMessage],
    error: Exception,
    *,
    provider: str,
    model: str,
) -> list[BaseMessage]:
    return [
        *input_messages,
        HumanMessage(
            content=model_request_recovery_instruction(error, provider=provider, model=model),
            name=RECOVERY_MESSAGE_NAME,
        ),
    ]


def model_request_recovery_instruction(error: Exception, *, provider: str, model: str) -> str:
    label = " / ".join(part for part in (provider, model) if part)
    detail = short_exception_text(error)
    return (
        "The previous provider request failed before an assistant reply because the current "
        f"{label or 'provider/model'} rejected an unsupported tool, capability, or optional request parameter.\n"
        f"Provider error: {detail}\n\n"
        "Answer the user's latest real request directly in natural language using the conversation and visible "
        "context. Do not call tools in this recovery reply. If the user asked for an unavailable artifact or "
        "capability, explain the limitation plainly and offer the closest useful text-only help, such as a prompt, "
        "outline, or next step. Match the user's language."
    )


def recovered_final_messages(
    chunks: list[object],
    recovery_messages: list[BaseMessage],
    original_input_messages: list[BaseMessage],
    error: Exception,
) -> list[BaseMessage]:
    final_messages = messages_from_final_chunk(chunks) or recovery_messages
    stripped = without_recovery_messages(final_messages)
    if last_assistant_text(stripped) is not None:
        return mark_latest_assistant_recovered(stripped, error)
    return [
        *original_input_messages,
        AIMessage(
            content=generic_recovery_response(error),
            response_metadata={"recovered_from_error": short_exception_text(error)},
        ),
    ]


def run_agent_loop_with_recovery(
    run_loop: Any,
    chat_model_for_config: Any,
    *,
    model: Any,
    input_messages: list[BaseMessage],
    tools: list[Any],
    model_config: AppConfig,
    system_prompt: Any,
    thread_id: str,
    run_config: dict[str, Any] | None,
    stream_mode: str,
    provider: str,
    model_name: str,
) -> tuple[list[Any], list[BaseMessage]]:
    try:
        chunks = list(
            run_loop(
                model,
                input_messages,
                tools=tools,
                app_config=model_config,
                system_prompt=system_prompt,
                thread_id=thread_id,
                run_config=run_config,
                stream_mode=stream_mode,
            )
        )
        return chunks, messages_from_final_chunk(chunks) or input_messages
    except Exception as error:
        if not is_recoverable_model_request_error(error):
            raise
        recovery_config = model_config_for_recovery(model_config)
        recovery_messages = messages_with_recovery_instruction(
            input_messages,
            error,
            provider=provider,
            model=model_name,
        )
        chunks = list(
            run_loop(
                chat_model_for_config(recovery_config),
                recovery_messages,
                tools=[],
                app_config=recovery_config,
                system_prompt=system_prompt,
                thread_id=thread_id,
                run_config=run_config,
                stream_mode=stream_mode,
            )
        )
        return chunks, recovered_final_messages(chunks, recovery_messages, input_messages, error)


def without_recovery_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    return [
        message
        for message in messages
        if not (isinstance(message, HumanMessage) and str(getattr(message, "name", "") or "") == RECOVERY_MESSAGE_NAME)
    ]


def mark_latest_assistant_recovered(messages: list[BaseMessage], error: Exception) -> list[BaseMessage]:
    updated = list(messages)
    for index in range(len(updated) - 1, -1, -1):
        message = updated[index]
        if not isinstance(message, AIMessage):
            continue
        metadata = dict(getattr(message, "response_metadata", None) or {})
        metadata.setdefault("recovered_from_error", short_exception_text(error))
        updated[index] = message.model_copy(update={"response_metadata": metadata})
        break
    return updated


def generic_recovery_response(error: Exception) -> str:
    return (
        "The current model could not use one of the requested capabilities for this turn. "
        f"Provider detail: {short_exception_text(error)}"
    )


def short_exception_text(error: BaseException, *, limit: int = 500) -> str:
    text = exception_text(error)
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


def exception_text(error: BaseException) -> str:
    return " ".join(str(error or "").split())


__all__ = [
    "RECOVERABLE_REQUEST_OPTION_KEYS",
    "RECOVERY_MESSAGE_NAME",
    "exception_text",
    "generic_recovery_response",
    "is_recoverable_model_request_error",
    "mark_latest_assistant_recovered",
    "messages_with_recovery_instruction",
    "model_config_for_recovery",
    "model_request_recovery_instruction",
    "recovered_final_messages",
    "run_agent_loop_with_recovery",
    "short_exception_text",
    "without_recovery_messages",
]
