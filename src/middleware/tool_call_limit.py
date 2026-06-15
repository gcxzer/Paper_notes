from __future__ import annotations

from typing import Literal

from langchain.agents.middleware import ToolCallLimitMiddleware as LangChainToolCallLimitMiddleware


DEFAULT_TOOL_CALL_LIMIT_EXIT_BEHAVIOR = "continue"
ToolCallLimitExitBehavior = Literal["continue", "error", "end"]


class ToolCallLimitMiddleware(LangChainToolCallLimitMiddleware):
    """Paper Notes wrapper around LangChain's official tool-call limiter."""


def create_tool_call_limit_middleware(
    *,
    tool_name: str | None = None,
    thread_limit: int | None = None,
    run_limit: int | None = None,
    exit_behavior: ToolCallLimitExitBehavior = DEFAULT_TOOL_CALL_LIMIT_EXIT_BEHAVIOR,
) -> ToolCallLimitMiddleware:
    return ToolCallLimitMiddleware(
        tool_name=tool_name,
        thread_limit=thread_limit,
        run_limit=run_limit,
        exit_behavior=exit_behavior,
    )


__all__ = [
    "DEFAULT_TOOL_CALL_LIMIT_EXIT_BEHAVIOR",
    "ToolCallLimitExitBehavior",
    "ToolCallLimitMiddleware",
    "create_tool_call_limit_middleware",
]
