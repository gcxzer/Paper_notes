"""说明：读取和判断正在运行的 agent run 恢复信息。

作用：让前端刷新后可以知道上一轮请求是否还在运行、是否完成或是否需要恢复展示。
"""

from __future__ import annotations

import copy
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from agent_runtime.messages import last_assistant_text, messages_from_final_chunk
from app_config import AppConfig

__all__ = [
    "is_recoverable_model_request_error",
    "messages_with_recovery_instruction",
    "model_config_for_recovery",
    "recovered_final_messages",
    "run_agent_loop_with_recovery",
    "short_exception_text",
]

RECOVERY_MESSAGE_NAME = "paper_notes_recovery"
RECOVERABLE_REQUEST_OPTION_KEYS = {
    "_paper_notes_image_generation",
    "imageGeneration",
    "image_generation",
    "_paper_notes_native_web_search",
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


# 可恢复错误识别
def is_recoverable_model_request_error(error: Exception) -> bool:
    """判断 provider 错误是否适合移除可选能力后重试。"""
    text = " ".join(str(error or "").split()).lower()
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


# 恢复用模型配置和提示
def model_config_for_recovery(config: AppConfig) -> AppConfig:
    """复制模型配置，并移除容易触发 provider 400 的可选参数。"""
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
    """在原输入后追加一条恢复说明，让模型用纯文本回答用户请求。"""
    return [
        *input_messages,
        HumanMessage(
            content=model_request_recovery_instruction(error, provider=provider, model=model),
            name=RECOVERY_MESSAGE_NAME,
        ),
    ]


def model_request_recovery_instruction(error: Exception, *, provider: str, model: str) -> str:
    """生成恢复重试时给模型看的系统化说明。"""
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


# 恢复结果整理
def recovered_final_messages(
    chunks: list[object],
    recovery_messages: list[BaseMessage],
    original_input_messages: list[BaseMessage],
    error: Exception,
) -> list[BaseMessage]:
    """从恢复重试 chunk 中提取最终消息，并标记 assistant 已从错误恢复。"""
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


def without_recovery_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """去掉内部恢复提示消息，避免它进入最终 transcript。"""
    return [
        message
        for message in messages
        if not (isinstance(message, HumanMessage) and str(getattr(message, "name", "") or "") == RECOVERY_MESSAGE_NAME)
    ]


def mark_latest_assistant_recovered(messages: list[BaseMessage], error: Exception) -> list[BaseMessage]:
    """给最近一条 assistant 消息加 recovered_from_error metadata。"""
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
    """当恢复重试没有 assistant 回复时生成兜底文本。"""
    return (
        "The current model could not use one of the requested capabilities for this turn. "
        f"Provider detail: {short_exception_text(error)}"
    )


# 执行带恢复的 agent loop
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
    middleware: list[Any] | None = None,
    paper_memory_context: dict[str, Any] | None = None,
) -> tuple[list[Any], list[BaseMessage]]:
    """执行 agent loop；遇到可恢复 provider 请求错误时降级配置并重试一次。"""
    try:
        chunks = list(
            run_loop(
                model,
                input_messages,
                tools=tools,
                app_config=model_config,
                system_prompt=system_prompt,
                middleware=middleware,
                paper_memory_context=paper_memory_context,
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
                middleware=middleware,
                paper_memory_context=paper_memory_context,
                thread_id=thread_id,
                run_config=run_config,
                stream_mode=stream_mode,
            )
        )
        return chunks, recovered_final_messages(chunks, recovery_messages, input_messages, error)


# 错误文本
def short_exception_text(error: BaseException, *, limit: int = 500) -> str:
    """返回适合保存和展示的短错误文本。"""
    text = " ".join(str(error or "").split())
    return text if len(text) <= limit else f"{text[:limit - 3]}..."
