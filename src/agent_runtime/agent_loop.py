"""Create and run LangChain agents with the Paper Notes middleware stack."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool

from app_config import AppConfig
from middleware import with_configured_middleware

__all__ = [
    "run_agent_loop",
]


def run_agent_loop(
    model: str | BaseChatModel,
    messages: Sequence[BaseMessage] | str,
    tools: Sequence[BaseTool | dict[str, Any]] | None = None,
    *,
    app_config: AppConfig | None = None,
    system_prompt: str | BaseMessage | None = None,
    middleware: Sequence[AgentMiddleware] | None = None,
    paper_memory_context: Mapping[str, Any] | None = None,
    thread_id: str = "default",
    run_config: dict[str, Any] | None = None,
    stream_mode: str = "values",
    stream_version: str | None = None,
) -> Iterator[Any]:
    """创建 LangChain agent，并按指定 stream_mode 产出原始 LangChain chunk。"""
    config = dict(run_config or {})
    configurable = dict(config.get("configurable") or {})
    configurable.setdefault("thread_id", thread_id)
    config["configurable"] = configurable

    resolved_middleware = with_configured_middleware(
        model=model,
        middleware=middleware,
        app_config=app_config,
        paper_memory_context=paper_memory_context,
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
    input_messages = [HumanMessage(content=messages)] if isinstance(messages, str) else list(messages)
    yield from agent.stream(
        {"messages": input_messages},
        config=config,
        **stream_kwargs,
    )
