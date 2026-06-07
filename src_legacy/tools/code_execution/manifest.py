from __future__ import annotations

from tools.toolsets import BUILTIN_TOOL_GROUPS


TOOL_NAME = "execute_code"
TOOLSET = "code_execution"
TOOL_GROUP = BUILTIN_TOOL_GROUPS[TOOLSET]


def register_tools(registry, **kwargs):
    from tools.code_execution.tool import register_code_execution_tool

    return register_code_execution_tool(registry, **kwargs)


__all__ = ["TOOL_GROUP", "TOOL_NAME", "TOOLSET", "register_tools"]
