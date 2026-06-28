"""说明：组装 Paper Notes agent 的系统提示词。

作用：把工具说明、长期记忆、当前论文记忆和阅读上下文合成模型调用时的指令。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_prompts.defaults import (
    PAPER_NOTES_AGENT_IDENTITY,
    PAPER_NOTES_GENERATED_ARTIFACT_GUIDANCE,
    PAPER_NOTES_NO_TOOL_GUIDANCE,
    PAPER_NOTES_RESPONSE_GUIDANCE,
    PAPER_NOTES_SEARCH_QUERY_GUIDANCE,
    PAPER_NOTES_TOOL_GUIDANCE,
    PAPER_NOTES_WRITING_WORKFLOW_GUIDANCE,
    TOOL_GUIDANCE_BY_NAME,
)
from agent_prompts.reading_context import AgentPromptContext, build_context_section, normalize_prompt_context
from memory import build_memory_section, build_paper_memory_section


def build_agent_instructions(
    *,
    tools: Sequence[Any] | None = None,
    context: AgentPromptContext | dict[str, Any] | None = None,
    extra_instructions: str | None = None,
    model: str = "",
) -> str:
    tool_names = extract_tool_names(tools or [])
    normalized_context = normalize_prompt_context(context)
    current_note = (
        normalized_context.current_note
        if normalized_context and isinstance(normalized_context.current_note, dict)
        else {}
    )
    current_note_id = str(current_note.get("id") or "").strip()
    parts = [
        PAPER_NOTES_AGENT_IDENTITY,
        PAPER_NOTES_RESPONSE_GUIDANCE,
        _build_tool_guidance(tool_names),
    ]
    if extra_instructions and extra_instructions.strip():
        parts.append(extra_instructions.strip())
    parts.append(build_memory_section())
    parts.append(build_paper_memory_section(current_note_id))
    parts.append(build_context_section(normalized_context))

    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def extract_tool_names(tools: Sequence[Any]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        if isinstance(tool, dict):
            function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            name = function.get("name") or tool.get("name") or tool.get("type")
        else:
            name = getattr(tool, "name", "")
        text = str(name).strip() if isinstance(name, str) else ""
        if text.startswith("web_search_"):
            text = "web_search"
        if text:
            names.add(text)
    return names


def _build_tool_guidance(tool_names: set[str]) -> str:
    if not tool_names:
        return PAPER_NOTES_NO_TOOL_GUIDANCE

    lines = [
        PAPER_NOTES_TOOL_GUIDANCE,
        "",
        "Available local tools:",
    ]
    for tool_name in sorted(tool_names):
        default_guidance = f"Use {tool_name} only when it directly helps answer the user."
        guidance = TOOL_GUIDANCE_BY_NAME.get(tool_name, default_guidance)
        guidance_lines = str(guidance).strip().splitlines()
        if len(guidance_lines) <= 1:
            lines.append(f"- {tool_name}: {guidance_lines[0] if guidance_lines else ''}")
        else:
            lines.append(f"- {tool_name}:")
            lines.extend(f"  {line}" if line else "" for line in guidance_lines)

    if "get_paper_context" in tool_names:
        lines.extend(["", PAPER_NOTES_SEARCH_QUERY_GUIDANCE])

    if {"write_note", "update_note_metadata", "manage_annotations", "write_note_media"} & tool_names:
        lines.extend(["", PAPER_NOTES_WRITING_WORKFLOW_GUIDANCE])

    if {"create_file_artifact", "create_image_artifact"} & tool_names:
        lines.extend(["", PAPER_NOTES_GENERATED_ARTIFACT_GUIDANCE])

    if {"web_search", "web_fetch"} & tool_names:
        lines.extend([
            "",
            "# External web lookup",
            "- Use web_search or web_fetch when local Paper Notes context is insufficient for current external facts.",
            "- Cite source URLs from tool output when using web results.",
        ])

    return "\n".join(lines)
