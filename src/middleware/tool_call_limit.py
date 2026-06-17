"""说明：限制单轮 agent 可发起的工具调用数量。

作用：防止模型陷入工具循环，并在达到上限时给出可控的停止行为。
"""

from __future__ import annotations

from typing import Literal

from langchain.agents.middleware import ToolCallLimitMiddleware as LangChainToolCallLimitMiddleware

__all__ = [
    "ToolCallLimitMiddleware",
    "create_tool_call_limit_middleware",
]

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
