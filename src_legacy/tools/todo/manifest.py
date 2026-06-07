from __future__ import annotations

from tools.toolsets import BUILTIN_TOOL_GROUPS


TOOL_GROUP = BUILTIN_TOOL_GROUPS["todo"]


def register_tools(registry, **kwargs):
    from tools.todo.tool import register_todo_tool

    return register_todo_tool(registry, **kwargs)


__all__ = ["TOOL_GROUP", "register_tools"]
