from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_prompts.defaults import (
    PAPER_NOTES_AGENT_IDENTITY,
    PAPER_NOTES_NO_TOOL_GUIDANCE,
    PAPER_NOTES_RESPONSE_GUIDANCE,
    PAPER_NOTES_SEARCH_QUERY_GUIDANCE,
    PAPER_NOTES_TOOL_GUIDANCE,
    PAPER_NOTES_WRITING_WORKFLOW_GUIDANCE,
    TOOL_GUIDANCE_BY_NAME,
)
from agent_prompts.reading_context import AgentPromptContext, build_context_section


def build_agent_instructions(
    *,
    tools: Sequence[Any] | None = None,
    context: AgentPromptContext | dict[str, Any] | None = None,
    extra_instructions: str | None = None,
    model: str = "",
) -> str:
    tool_names = extract_tool_names(tools or [])
    parts = [
        PAPER_NOTES_AGENT_IDENTITY,
        PAPER_NOTES_RESPONSE_GUIDANCE,
        _build_tool_guidance(tool_names),
    ]
    if extra_instructions and extra_instructions.strip():
        parts.append(extra_instructions.strip())
    parts.append(build_context_section(context))

    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def extract_tool_names(tools: Sequence[Any]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        name = _extract_tool_name(tool)
        if name:
            names.add(name)
    return names


def _extract_tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = function.get("name") or tool.get("name")
    else:
        name = getattr(tool, "name", "")
    return str(name).strip() if isinstance(name, str) else ""


def _build_tool_guidance(tool_names: set[str]) -> str:
    if not tool_names:
        return PAPER_NOTES_NO_TOOL_GUIDANCE

    lines = [
        PAPER_NOTES_TOOL_GUIDANCE,
        "",
        "Available local tools:",
    ]
    for tool_name in sorted(tool_names):
        guidance = TOOL_GUIDANCE_BY_NAME.get(tool_name, f"Use {tool_name} only when it directly helps answer the user.")
        lines.append(f"- {tool_name}: {guidance}")

    if "search_notes" in tool_names:
        lines.extend(["", PAPER_NOTES_SEARCH_QUERY_GUIDANCE])

    if {"write_note", "manage_annotations", "write_note_media"} & tool_names:
        lines.extend(["", PAPER_NOTES_WRITING_WORKFLOW_GUIDANCE])

    return "\n".join(lines)
