from __future__ import annotations

from tools.toolsets import BUILTIN_TOOL_GROUPS


TOOL_GROUP = BUILTIN_TOOL_GROUPS["persistent_memory"]


def register_tools(registry, *, handler):
    from tools.persistent_memory.tool import create_persistent_memory_tool_definition

    registry.register_group(TOOL_GROUP)
    if registry.get("persistent_memory") is None:
        registry.register(create_persistent_memory_tool_definition(handler))


__all__ = ["TOOL_GROUP", "register_tools"]
