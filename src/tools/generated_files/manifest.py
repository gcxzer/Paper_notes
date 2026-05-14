from __future__ import annotations

from tools.toolsets import BUILTIN_TOOL_GROUPS


TOOL_NAME = "create_file_artifact"
TOOLSET = "generated_artifacts"
TOOL_GROUP = BUILTIN_TOOL_GROUPS[TOOLSET]


def register_tools(registry, **kwargs):
    from tools.generated_files.tool import register_generated_file_tool

    return register_generated_file_tool(registry, **kwargs)


__all__ = ["TOOL_GROUP", "TOOL_NAME", "TOOLSET", "register_tools"]
