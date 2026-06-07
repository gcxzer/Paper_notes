from __future__ import annotations

from tools.toolsets import BUILTIN_TOOL_GROUPS


TOOL_GROUP = BUILTIN_TOOL_GROUPS["web_search"]


def register_tools(registry, **kwargs):
    from tools.web_search.tool import register_web_search_tool

    return register_web_search_tool(registry, **kwargs)


__all__ = ["TOOL_GROUP", "register_tools"]
