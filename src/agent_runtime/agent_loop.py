from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool

from app_config import AppConfig
from middleware import (
    ContextCollapseMiddleware,
    ContextCompactionMiddleware,
    DEFAULT_COMPACTION_RESERVE_TOKENS,
    compaction_trigger_tokens,
    create_context_collapse_middleware,
    create_context_compaction_middleware,
)
from model_providers.core.types import ModelProviderConfig


def run_agent_loop(
    model: str | BaseChatModel,
    messages: Sequence[BaseMessage] | str,
    tools: Sequence[BaseTool] | None = None,
    *,
    app_config: AppConfig | None = None,
    system_prompt: str | BaseMessage | None = None,
    middleware: Sequence[AgentMiddleware] | None = None,
    thread_id: str = "default",
    run_config: dict[str, Any] | None = None,
    stream_mode: str = "values",
    debug: bool = False,
) -> Iterator[Any]:
    config = _with_thread_id(run_config, thread_id)
    resolved_middleware = _with_context_management(
        model=model,
        middleware=middleware,
        app_config=app_config,
    )
    agent = create_agent(
        model=model,
        tools=list(tools or []),
        system_prompt=system_prompt,
        middleware=resolved_middleware,
        debug=debug,
    )
    yield from agent.stream(
        {"messages": _coerce_messages(messages)},
        config=config,
        stream_mode=stream_mode,
    )


def _coerce_messages(messages: Sequence[BaseMessage] | str) -> list[BaseMessage]:
    if isinstance(messages, str):
        return [HumanMessage(content=messages)]
    return list(messages)


def _with_thread_id(run_config: dict[str, Any] | None, thread_id: str) -> dict[str, Any]:
    config = dict(run_config or {})
    configurable = dict(config.get("configurable") or {})
    configurable.setdefault("thread_id", thread_id)
    config["configurable"] = configurable
    return config


def _with_context_management(
    *,
    model: str | BaseChatModel,
    middleware: Sequence[AgentMiddleware] | None,
    app_config: AppConfig | None,
) -> list[AgentMiddleware]:
    resolved = list(middleware or [])
    if app_config is None:
        return resolved
    if _config_bool(app_config, "context_management.enabled", "contextManagement.enabled", default=True) is False:
        return resolved

    try:
        model_config = ModelProviderConfig.from_app_config(app_config)
    except Exception:
        return resolved

    reserve_tokens = _config_int(
        app_config,
        "context_compaction.reserve_tokens",
        "contextCompaction.reserveTokens",
        default=DEFAULT_COMPACTION_RESERVE_TOKENS,
    )
    trigger_tokens = compaction_trigger_tokens(
        _resolve_context_window(model_config.provider, model_config.model),
        reserve_tokens,
    )
    if not _has_context_collapse_middleware(resolved):
        _insert_before_compaction(
            resolved,
            create_context_collapse_middleware(
                model,
                trigger=("tokens", trigger_tokens),
            ),
        )
    if not _has_context_compaction_middleware(resolved):
        resolved.append(
            create_context_compaction_middleware(
                model,
                provider=model_config.provider,
                model_name=model_config.model,
                reserve_tokens=reserve_tokens,
            )
        )
    return resolved


def _resolve_context_window(provider: str, model_name: str) -> int:
    from model_providers import resolve_context_length_for_model

    return resolve_context_length_for_model(provider, model_name)


def _has_context_collapse_middleware(middleware: Sequence[AgentMiddleware]) -> bool:
    return any(isinstance(item, ContextCollapseMiddleware) for item in middleware)


def _has_context_compaction_middleware(middleware: Sequence[AgentMiddleware]) -> bool:
    return any(isinstance(item, ContextCompactionMiddleware) for item in middleware)


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


def _config_int(app_config: AppConfig, *keys: str, default: int) -> int:
    for key in keys:
        value = app_config.get(key, None)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return default
