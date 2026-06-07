from __future__ import annotations

from tools.toolsets import BUILTIN_TOOL_GROUPS


TOOL_GROUP = BUILTIN_TOOL_GROUPS["session_search"]


def register_tools(registry, **kwargs):
    from tools.session_search.tool import register_session_search_tool

    return register_session_search_tool(registry, **kwargs)


__all__ = ["TOOL_GROUP", "register_tools"]
