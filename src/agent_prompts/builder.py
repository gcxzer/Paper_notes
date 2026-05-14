from __future__ import annotations

from typing import Any

from agent_prompts.context import AgentPromptContext, build_context_section
from agent_prompts.defaults import (
    OPENAI_TOOL_PERSISTENCE_GUIDANCE,
    PAPER_NOTES_AGENT_IDENTITY,
    PAPER_NOTES_CODE_EXECUTION_GUIDANCE,
    PAPER_NOTES_MANDATORY_TOOL_USE_GUIDANCE,
    PAPER_NOTES_MEMORY_GUIDANCE,
    PAPER_NOTES_NO_TOOL_GUIDANCE,
    PAPER_NOTES_RESPONSE_GUIDANCE,
    PAPER_NOTES_SEARCH_QUERY_GUIDANCE,
    PAPER_NOTES_TODO_GUIDANCE,
    PAPER_NOTES_TOOL_USE_ENFORCEMENT_GUIDANCE,
    PAPER_NOTES_TOOL_USE_GUIDANCE,
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
                PAPER_NOTES_MANDATORY_TOOL_USE_GUIDANCE,
            ])
        return PAPER_NOTES_NO_TOOL_GUIDANCE

    lines = [
        PAPER_NOTES_TOOL_USE_GUIDANCE,
        "",
        PAPER_NOTES_TOOL_USE_ENFORCEMENT_GUIDANCE,
        "",
        PAPER_NOTES_MANDATORY_TOOL_USE_GUIDANCE,
    ]
    if native_web_search_enabled:
        lines.extend(["", PROVIDER_NATIVE_WEB_SEARCH_GUIDANCE])
    lines.extend(["", "Available local tools:"])
    for tool_name in sorted(tool_names):
        guidance = TOOL_GUIDANCE_BY_NAME.get(tool_name, f"Use {tool_name} only when it directly helps answer the user.")
        lines.append(f"- {tool_name}: {guidance}")

    if "paper_notes_search" in tool_names:
        lines.extend(["", PAPER_NOTES_SEARCH_QUERY_GUIDANCE])

    if "paper_notes_edit" in tool_names or "execute_code" in tool_names:
        lines.extend(["", PAPER_NOTES_WRITING_WORKFLOW_GUIDANCE])

    if "execute_code" in tool_names:
        lines.extend(["", PAPER_NOTES_CODE_EXECUTION_GUIDANCE])

    model_lower = model.lower()
    if "gpt" in model_lower or "codex" in model_lower:
        lines.extend(["", _build_openai_tool_persistence_section(
            tool_names,
            native_web_search_enabled=native_web_search_enabled,
        )])

    return "\n".join(lines)


def _build_openai_tool_persistence_section(
    tool_names: set[str],
    *,
    native_web_search_enabled: bool = False,
) -> str:
    lines = [OPENAI_TOOL_PERSISTENCE_GUIDANCE]
    suggestions: list[str] = []
    if native_web_search_enabled:
        suggestions.append(
            "- Use provider-native web search for current external web facts when local Paper Notes context is not enough."
        )
    if "paper_notes_search" in tool_names:
        suggestions.append(
            "- Use paper_notes_search to find candidate papers. For non-English requests, rewrite the query as "
            "English-first paper keywords plus important original terms."
        )
    if "paper_notes_context" in tool_names:
        suggestions.append(
            "- Use paper_notes_context before answering detailed note questions or before editing note content."
        )
    if "paper_notes_read_paper" in tool_names:
        suggestions.append(
            "- Use paper_notes_read_paper when the answer depends on PDF text, page images, figures, or visual analysis."
        )
    if "paper_notes_edit" in tool_names:
        suggestions.append(
            "- Use paper_notes_edit only when the user clearly wants local note, metadata, or annotation changes."
        )
        suggestions.append(
            "- To insert a generated or uploaded image artifact into a note, call paper_notes_edit with action "
            "insert_image and the artifact_id; do not write local .paper-notes file paths into note HTML."
        )
    if "paper_notes_review" in tool_names:
        suggestions.append("- Use paper_notes_review to validate saved note HTML or preview a note diff without writing.")
    if "session_search" in tool_names:
        suggestions.append(
            "- Use session_search for previous task progress or past decisions instead of storing those in memory."
        )
    if "persistent_memory" in tool_names:
        suggestions.append("- Use persistent_memory only for durable preferences, corrections, and project conventions.")
    if "todo" in tool_names:
        suggestions.append("- Use todo for multi-step current-session work, not durable memory.")
    if "skills_list" in tool_names and "skill_view" in tool_names:
        suggestions.append(
            "- If the user names a specific local skill, use skill_view directly; use skills_list first only when "
            "discovering or choosing among skills."
        )
        suggestions.append(
            "- After skill_view, follow the loaded skill instructions and open linked files only when the task needs them."
        )
    if "execute_code" in tool_names:
        suggestions.append(
            "- Use execute_code for bounded Python calculations, small data transforms, or note edits through "
            "paper_notes_tools.paper_notes_edit when that helper is available; do not describe it as a strong sandbox."
        )
    if "web_search" in tool_names:
        suggestions.append(
            "- Use custom web_search for external web facts when native web search is unavailable or disabled; "
            "runtime provider priority is Tavily, then Brave Search."
        )
    if "web_fetch" in tool_names:
        suggestions.append(
            "- Use web_fetch to read a specific public URL supplied by the user, or to inspect selected sources after "
            "web_search when snippets are not enough."
        )
    if suggestions:
        lines.extend(["", "Preferred local tool flow:", *suggestions])
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
