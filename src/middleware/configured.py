"""说明：根据模型和配置组装 middleware 列表。

作用：把上下文压缩、工具输出处理、论文记忆等能力按 AppConfig 开关接入 agent。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel

from app_config import AppConfig
from middleware.compaction import (
    DEFAULT_COMPACTION_RESERVE_TOKENS,
    ContextCompactionMiddleware,
    create_context_compaction_middleware,
)
from middleware.context_collapse import (
    DEFAULT_CONTEXT_COLLAPSE_KEEP,
    DEFAULT_CONTEXT_COLLAPSE_KEEP_TO_PREVIOUS_USER_QUESTION,
    DEFAULT_CONTEXT_COLLAPSE_TRIGGER_MESSAGES,
    DEFAULT_CONTEXT_COLLAPSE_TRIGGER_TOKENS,
    ContextCollapseMiddleware,
    create_context_collapse_middleware,
)
from middleware.paper_memory import (
    DEFAULT_PAPER_MEMORY_UPDATE_INTERVAL,
    PaperMemoryMiddleware,
    create_paper_memory_middleware,
)
from middleware.rag_tool_serialization import (
    DEFAULT_SERIALIZED_RAG_TOOLS,
    RagToolSerializationMiddleware,
    create_rag_tool_serialization_middleware,
)
from middleware.tool_output_placeholder import (
    ToolOutputPlaceholderMiddleware,
    create_tool_output_placeholder_middleware,
)
from middleware.tool_call_limit import (
    ToolCallLimitMiddleware,
    create_tool_call_limit_middleware,
)
from middleware.tool_output_truncation import (
    ToolOutputTruncationMiddleware,
    create_tool_output_truncation_middleware,
)
from model_providers.core.types import ModelProviderConfig

__all__ = [
    "with_configured_middleware",
]

def with_configured_middleware(
    *,
    model: str | BaseChatModel,
    middleware: Sequence[AgentMiddleware] | None,
    app_config: AppConfig | None,
    paper_memory_context: Mapping[str, Any] | None = None,
) -> list[AgentMiddleware]:
    resolved = list(middleware or [])
    if app_config is None:
        return resolved
    if _tool_output_enabled(app_config):
        _insert_tool_output_middleware(resolved, app_config)
    if _rag_tool_serialization_enabled(app_config):
        _insert_rag_tool_serialization_middleware(resolved, app_config)
    if _tool_call_limit_enabled(app_config):
        _insert_tool_call_limit_middleware(resolved, app_config)
    if _paper_memory_enabled(app_config):
        _insert_paper_memory_middleware(resolved, model, app_config, paper_memory_context)
    if _config_bool(app_config, "context_management.enabled", "contextManagement.enabled", default=True) is False:
        return resolved

    try:
        model_config = ModelProviderConfig.from_app_config(app_config)
    except Exception:
        return resolved

    if not _has_context_collapse_middleware(resolved):
        _insert_before_compaction(resolved, _context_collapse_middleware(model, app_config))
    if not _has_context_compaction_middleware(resolved):
        resolved.append(_context_compaction_middleware(model, app_config, model_config))
    return resolved


def _has_context_collapse_middleware(middleware: Sequence[AgentMiddleware]) -> bool:
    return any(isinstance(item, ContextCollapseMiddleware) for item in middleware)


def _has_context_compaction_middleware(middleware: Sequence[AgentMiddleware]) -> bool:
    return any(isinstance(item, ContextCompactionMiddleware) for item in middleware)


def _has_tool_output_truncation_middleware(middleware: Sequence[AgentMiddleware]) -> bool:
    return any(isinstance(item, ToolOutputTruncationMiddleware) for item in middleware)


def _has_tool_output_placeholder_middleware(middleware: Sequence[AgentMiddleware]) -> bool:
    return any(isinstance(item, ToolOutputPlaceholderMiddleware) for item in middleware)


def _has_tool_call_limit_middleware(middleware: Sequence[AgentMiddleware], *, tool_name: str | None) -> bool:
    return any(
        isinstance(item, ToolCallLimitMiddleware) and getattr(item, "tool_name", None) == tool_name
        for item in middleware
    )


def _has_paper_memory_middleware(middleware: Sequence[AgentMiddleware]) -> bool:
    return any(isinstance(item, PaperMemoryMiddleware) for item in middleware)


def _has_rag_tool_serialization_middleware(middleware: Sequence[AgentMiddleware]) -> bool:
    return any(isinstance(item, RagToolSerializationMiddleware) for item in middleware)


def _tool_output_enabled(app_config: AppConfig) -> bool:
    return _config_bool(app_config, "tool_output.enabled", "toolOutput.enabled", default=True)


def _rag_tool_serialization_enabled(app_config: AppConfig) -> bool:
    return _config_bool(
        app_config,
        "rag_tool_serialization.enabled",
        "ragToolSerialization.enabled",
        default=True,
    )


def _tool_call_limit_enabled(app_config: AppConfig) -> bool:
    config = app_config.tool_call_limit
    return bool(config and config.enabled and config.limits)


def _paper_memory_enabled(app_config: AppConfig) -> bool:
    return _config_bool(app_config, "paper_memory.enabled", "paperMemory.enabled", default=True)


def _insert_tool_output_middleware(middleware: list[AgentMiddleware], app_config: AppConfig) -> None:
    insert_at = 0
    if not _has_tool_output_truncation_middleware(middleware):
        middleware.insert(insert_at, _tool_output_truncation_middleware(app_config))
        insert_at += 1
    if not _has_tool_output_placeholder_middleware(middleware):
        middleware.insert(insert_at, _tool_output_placeholder_middleware(app_config))


def _insert_rag_tool_serialization_middleware(middleware: list[AgentMiddleware], app_config: AppConfig) -> None:
    if _has_rag_tool_serialization_middleware(middleware):
        return
    middleware.append(
        create_rag_tool_serialization_middleware(
            tool_names=_rag_tool_serialization_tool_names(app_config),
        )
    )


def _insert_tool_call_limit_middleware(middleware: list[AgentMiddleware], app_config: AppConfig) -> None:
    config = app_config.tool_call_limit
    if config is None:
        return
    for rule in config.limits:
        if _has_tool_call_limit_middleware(middleware, tool_name=rule.tool_name):
            continue
        middleware.append(
            create_tool_call_limit_middleware(
                tool_name=rule.tool_name,
                thread_limit=rule.thread_limit,
                run_limit=rule.run_limit,
                exit_behavior=rule.exit_behavior,
            )
        )


def _insert_paper_memory_middleware(
    middleware: list[AgentMiddleware],
    model: str | BaseChatModel,
    app_config: AppConfig,
    paper_memory_context: Mapping[str, Any] | None,
) -> None:
    if _has_paper_memory_middleware(middleware):
        return
    note_id = _context_text(paper_memory_context, "note_id", "noteId")
    if not note_id:
        return
    middleware.append(
        create_paper_memory_middleware(
            model,
            note_id=note_id,
            note_title=_context_text(paper_memory_context, "note_title", "noteTitle"),
            session_id=_context_text(paper_memory_context, "session_id", "sessionId"),
            memory_dir=_paper_memory_dir(app_config),
            update_interval=_paper_memory_update_interval(app_config),
        )
    )


def _tool_output_truncation_middleware(app_config: AppConfig) -> ToolOutputTruncationMiddleware:
    config = app_config.tool_output
    return create_tool_output_truncation_middleware(
        root_dir=config.root_dir,
        default_max_tokens=config.default_max_tokens,
        tool_limits=config.tool_limits,
    )


def _tool_output_placeholder_middleware(app_config: AppConfig) -> ToolOutputPlaceholderMiddleware:
    return create_tool_output_placeholder_middleware(keep_recent=app_config.tool_output.placeholder_keep_recent)


def _context_collapse_middleware(model: str | BaseChatModel, app_config: AppConfig) -> ContextCollapseMiddleware:
    trigger_messages = _config_int(
        app_config,
        "context_collapse.trigger_messages",
        "contextCollapse.triggerMessages",
        default=DEFAULT_CONTEXT_COLLAPSE_TRIGGER_MESSAGES,
        minimum=1,
    )
    trigger_tokens = _config_int(
        app_config,
        "context_collapse.trigger_tokens",
        "contextCollapse.triggerTokens",
        default=DEFAULT_CONTEXT_COLLAPSE_TRIGGER_TOKENS,
        minimum=1,
    )
    return create_context_collapse_middleware(
        model,
        trigger=[("messages", trigger_messages), ("tokens", trigger_tokens)],
        keep=DEFAULT_CONTEXT_COLLAPSE_KEEP,
        keep_to_previous_user_question=DEFAULT_CONTEXT_COLLAPSE_KEEP_TO_PREVIOUS_USER_QUESTION,
    )


def _context_compaction_middleware(
    model: str | BaseChatModel,
    app_config: AppConfig,
    model_config: ModelProviderConfig,
) -> ContextCompactionMiddleware:
    reserve_tokens = _config_int(
        app_config,
        "context_compaction.reserve_tokens",
        "contextCompaction.reserveTokens",
        default=DEFAULT_COMPACTION_RESERVE_TOKENS,
    )
    return create_context_compaction_middleware(
        model,
        provider=model_config.provider,
        model_name=model_config.model,
        reserve_tokens=reserve_tokens,
    )


def _paper_memory_update_interval(app_config: AppConfig) -> int:
    return _config_int(
        app_config,
        "paper_memory.update_interval",
        "paperMemory.updateInterval",
        default=DEFAULT_PAPER_MEMORY_UPDATE_INTERVAL,
        minimum=1,
    )


def _paper_memory_dir(app_config: AppConfig) -> Path | None:
    value = app_config.get("paper_memory.dir", None)
    if value is None:
        value = app_config.get("paperMemory.dir", None)
    text = str(value or "").strip()
    return Path(text).expanduser() if text else None


def _rag_tool_serialization_tool_names(app_config: AppConfig) -> tuple[str, ...]:
    value = app_config.get("rag_tool_serialization.tool_names", None)
    if value is None:
        value = app_config.get("rag_tool_serialization.tools", None)
    if value is None:
        value = app_config.get("ragToolSerialization.toolNames", None)
    if value is None:
        value = app_config.get("ragToolSerialization.tools", None)
    names = _config_string_tuple(value)
    return names or DEFAULT_SERIALIZED_RAG_TOOLS


def _insert_before_compaction(middleware: list[AgentMiddleware], item: AgentMiddleware) -> None:
    for index, existing in enumerate(middleware):
        if isinstance(existing, ContextCompactionMiddleware):
            middleware.insert(index, item)
            return
    middleware.append(item)


def _context_text(context: Mapping[str, Any] | None, *keys: str) -> str:
    if context is None:
        return ""
    for key in keys:
        text = str(context.get(key) or "").strip()
        if text:
            return text
    return ""


def _config_bool(app_config: AppConfig, *keys: str, default: bool) -> bool:
    for key in keys:
        value = app_config.get(key, None)
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)
    return default


def _config_int(app_config: AppConfig, *keys: str, default: int, minimum: int = 0) -> int:
    for key in keys:
        value = app_config.get(key, None)
        if value is None:
            continue
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            continue
    return default


def _config_string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = value.split(",")
    elif isinstance(value, Sequence):
        raw_values = value
    else:
        return ()
    return tuple(text for item in raw_values if (text := str(item or "").strip()))
