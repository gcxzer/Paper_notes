from __future__ import annotations

from typing import Any

from agent_prompts.context import AgentPromptContext, build_context_section
from agent_prompts.defaults import (
    PAPER_NOTES_AGENT_IDENTITY,
    PAPER_NOTES_CODE_EXECUTION_GUIDANCE,
    PAPER_NOTES_MEMORY_GUIDANCE,
    PAPER_NOTES_MCP_GUIDANCE,
    PAPER_NOTES_NO_TOOL_GUIDANCE,
    PAPER_NOTES_RESPONSE_GUIDANCE,
    PAPER_NOTES_SEARCH_QUERY_GUIDANCE,
    PAPER_NOTES_TODO_GUIDANCE,
    PAPER_NOTES_TOOL_GUIDANCE,
    PAPER_NOTES_WRITING_WORKFLOW_GUIDANCE,
    PROVIDER_NATIVE_WEB_SEARCH_GUIDANCE,
    TOOL_GUIDANCE_BY_NAME,
)


def build_agent_instructions(
    *,
    tools: list[dict[str, Any]] | None = None,
    context: AgentPromptContext | dict[str, Any] | None = None,
    extra_instructions: str | None = None,
    model: str = "",
    memory_context: str = "",
    todo_context: str = "",
    native_web_search_enabled: bool = False,
) -> str:
    tool_names = extract_tool_names(tools or [])
    parts = [
        PAPER_NOTES_AGENT_IDENTITY,
        PAPER_NOTES_RESPONSE_GUIDANCE,
        _build_memory_section(memory_context, tool_names),
        _build_tool_guidance(tool_names, model=model, native_web_search_enabled=native_web_search_enabled),
        _build_todo_section(todo_context, tool_names),
        build_context_section(context),
    ]
    if extra_instructions and extra_instructions.strip():
        parts.append(extra_instructions.strip())
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def extract_tool_names(tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = function.get("name") or tool.get("name")
        if isinstance(name, str) and name.strip():
            names.add(name.strip())
    return names


def _build_tool_guidance(
    tool_names: set[str],
    *,
    model: str = "",
    native_web_search_enabled: bool = False,
) -> str:
    if not tool_names:
        if native_web_search_enabled:
            return "\n\n".join([
                PAPER_NOTES_NO_TOOL_GUIDANCE,
                PROVIDER_NATIVE_WEB_SEARCH_GUIDANCE,
                PAPER_NOTES_TOOL_GUIDANCE,
            ])
        return PAPER_NOTES_NO_TOOL_GUIDANCE

    lines = [
        PAPER_NOTES_TOOL_GUIDANCE,
    ]
    if native_web_search_enabled:
        lines.extend(["", PROVIDER_NATIVE_WEB_SEARCH_GUIDANCE])
    lines.extend(["", "Available local tools:"])
    for tool_name in sorted(tool_names):
        guidance = TOOL_GUIDANCE_BY_NAME.get(tool_name, f"Use {tool_name} only when it directly helps answer the user.")
        lines.append(f"- {tool_name}: {guidance}")

    if "search_notes" in tool_names:
        lines.extend(["", PAPER_NOTES_SEARCH_QUERY_GUIDANCE])

    if {"write_note", "manage_annotations", "write_note_media"} & tool_names:
        lines.extend(["", PAPER_NOTES_WRITING_WORKFLOW_GUIDANCE])

    if "execute_code" in tool_names:
        lines.extend(["", PAPER_NOTES_CODE_EXECUTION_GUIDANCE])

    if any(tool_name.startswith("mcp_") for tool_name in tool_names):
        lines.extend(["", PAPER_NOTES_MCP_GUIDANCE])

    return "\n".join(lines)


def _build_memory_section(memory_context: str, tool_names: set[str]) -> str:
    has_memory_context = bool(memory_context and memory_context.strip())
    if "persistent_memory" not in tool_names and not has_memory_context:
        return ""
    parts = [PAPER_NOTES_MEMORY_GUIDANCE]
    if has_memory_context:
        parts.append(memory_context.strip())
    return "\n\n".join(parts)


def _build_todo_section(todo_context: str, tool_names: set[str]) -> str:
    has_todo_context = bool(todo_context and todo_context.strip())
    if "todo" not in tool_names and not has_todo_context:
        return ""
    parts = [PAPER_NOTES_TODO_GUIDANCE]
    if has_todo_context:
        parts.append(f"<todo-context>\n{todo_context.strip()}\n</todo-context>")
    return "\n\n".join(parts)
