from __future__ import annotations

# Manifest hook that lets the global tool registry discover Paper Notes tools.

from tools.toolsets import BUILTIN_TOOL_GROUPS


TOOL_GROUP = BUILTIN_TOOL_GROUPS["paper_notes"]


def register_tools(registry, **kwargs):
    from tools.paper_notes.tool import create_paper_notes_registry

    return create_paper_notes_registry(registry, **kwargs)


__all__ = ["TOOL_GROUP", "register_tools"]
