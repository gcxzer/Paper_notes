from __future__ import annotations

from tools.toolsets import BUILTIN_TOOL_GROUPS


TOOL_GROUP = BUILTIN_TOOL_GROUPS["skills"]


def register_tools(registry, **kwargs):
    from tools.skills.tool import register_skills_tools

    return register_skills_tools(registry, **kwargs)


__all__ = ["TOOL_GROUP", "register_tools"]
