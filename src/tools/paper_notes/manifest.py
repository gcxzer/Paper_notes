from __future__ import annotations

from tools.toolsets import BUILTIN_TOOL_GROUPS


TOOL_GROUP = BUILTIN_TOOL_GROUPS["paper_notes"]


def register_tools(registry, **kwargs):
    from tools.paper_notes.tool import register_paper_notes_tools

    return register_paper_notes_tools(registry, **kwargs)


__all__ = ["TOOL_GROUP", "register_tools"]
