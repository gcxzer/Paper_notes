from __future__ import annotations

from collections.abc import Sequence

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
from middleware.tool_output_placeholder import (
    ToolOutputPlaceholderMiddleware,
    create_tool_output_placeholder_middleware,
)
from middleware.tool_output_truncation import (
    ToolOutputTruncationMiddleware,
    create_tool_output_truncation_middleware,
)
from model_providers.core.types import ModelProviderConfig


def with_configured_middleware(
    *,
    model: str | BaseChatModel,
    middleware: Sequence[AgentMiddleware] | None,
    app_config: AppConfig | None,
) -> list[AgentMiddleware]:
    resolved = list(middleware or [])
    if app_config is None:
        return resolved
    if _tool_output_enabled(app_config):
        _insert_tool_output_middleware(resolved, app_config)
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


def _tool_output_enabled(app_config: AppConfig) -> bool:
    return _config_bool(app_config, "tool_output.enabled", "toolOutput.enabled", default=True)


def _insert_tool_output_middleware(middleware: list[AgentMiddleware], app_config: AppConfig) -> None:
    insert_at = 0
    if not _has_tool_output_truncation_middleware(middleware):
        middleware.insert(insert_at, _tool_output_truncation_middleware(app_config))
        insert_at += 1
    if not _has_tool_output_placeholder_middleware(middleware):
        middleware.insert(insert_at, _tool_output_placeholder_middleware(app_config))


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


def _insert_before_compaction(middleware: list[AgentMiddleware], item: AgentMiddleware) -> None:
    for index, existing in enumerate(middleware):
        if isinstance(existing, ContextCompactionMiddleware):
            middleware.insert(index, item)
            return
    middleware.append(item)


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


__all__ = ["with_configured_middleware"]
