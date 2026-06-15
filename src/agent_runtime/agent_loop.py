from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool

from app_config import AppConfig
from middleware import with_configured_middleware


def run_agent_loop(
    model: str | BaseChatModel,
    messages: Sequence[BaseMessage] | str,
    tools: Sequence[BaseTool | dict[str, Any]] | None = None,
    *,
    app_config: AppConfig | None = None,
    system_prompt: str | BaseMessage | None = None,
    middleware: Sequence[AgentMiddleware] | None = None,
    thread_id: str = "default",
    run_config: dict[str, Any] | None = None,
    stream_mode: str = "values",
    stream_version: str | None = None,
) -> Iterator[Any]:
    config = _with_thread_id(run_config, thread_id)
    resolved_middleware = with_context_management(
        model=model,
        middleware=middleware,
        app_config=app_config,
    )
    agent = create_agent(
        model=model,
        tools=list(tools or []),
        system_prompt=system_prompt,
        middleware=resolved_middleware,
    )
    stream_kwargs: dict[str, Any] = {"stream_mode": stream_mode}
    if stream_version:
        stream_kwargs["version"] = stream_version
    yield from agent.stream(
        {"messages": _coerce_messages(messages)},
        config=config,
        **stream_kwargs,
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


def with_context_management(
    *,
    model: str | BaseChatModel,
    middleware: Sequence[AgentMiddleware] | None,
    app_config: AppConfig | None,
) -> list[AgentMiddleware]:
    return with_configured_middleware(model=model, middleware=middleware, app_config=app_config)


_with_context_management = with_context_management


__all__ = ["run_agent_loop", "with_context_management"]
