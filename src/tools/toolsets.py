from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from tools.registry import ToolRegistry
from tools.types import ToolGroupDefinition


@dataclass(frozen=True, slots=True)
class ToolsetDefinition:
    name: str
    description: str
    tools: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()


BUILTIN_TOOLSETS: dict[str, ToolsetDefinition] = {
    "paper_notes": ToolsetDefinition(
        name="paper_notes",
        description="Paper Notes library, PDF text and images, note, annotation retrieval, and safe note-writing tools.",
        tools=(
            "paper_notes_search",
            "paper_notes_context",
            "paper_notes_read_paper",
            "paper_notes_review",
        ),
    ),
    "paper_notes_internal": ToolsetDefinition(
        name="paper_notes_internal",
        description="Internal low-level Paper Notes tools for tests and debugging.",
        tools=(
            "search_library",
            "get_note",
            "read_annotations",
            "read_note_html",
            "list_note_sections",
            "search_paper_text",
            "read_paper_text",
            "render_paper_page",
            "extract_paper_images",
            "analyze_paper_image",
            "build_note_context",
            "validate_note_html",
            "preview_note_diff",
            "write_note_from_paper_image",
            "write_note_section",
            "append_note_section",
            "replace_note_section",
            "update_note_metadata",
        ),
    ),
    "readonly": ToolsetDefinition(
        name="readonly",
        description="Read-only tools for library, note, annotation, and past-session lookup.",
        tools=(
            "paper_notes_search",
            "paper_notes_context",
            "paper_notes_read_paper",
            "paper_notes_review",
            "session_search",
        ),
    ),
    "persistent_memory": ToolsetDefinition(
        name="persistent_memory",
        description="Durable user and project memory tools.",
        tools=("persistent_memory",),
    ),
    "session_search": ToolsetDefinition(
        name="session_search",
        description="Past transcript recall tools.",
        tools=("session_search",),
    ),
    "todo": ToolsetDefinition(
        name="todo",
        description="Session-local todo and planning tools.",
        tools=("todo",),
    ),
    "skills": ToolsetDefinition(
        name="skills",
        description="Local agent skills discovery and progressive instruction loading tools.",
        tools=("skills_list", "skill_view"),
    ),
    "code_execution": ToolsetDefinition(
        name="code_execution",
        description=(
            "Run local Python code in a temporary directory with light process guardrails "
            "and read-only Paper Notes tool RPC."
        ),
        tools=("execute_code",),
    ),
    "web_search": ToolsetDefinition(
        name="web_search",
        description=(
            "Configured custom web search and public URL fetch tools. "
            "If multiple custom search providers are enabled, Tavily runs before Brave Search."
        ),
        tools=("web_search", "web_fetch"),
    ),
    "generated_artifacts": ToolsetDefinition(
        name="generated_artifacts",
        description="On-demand generated image and text-file artifact tools.",
        tools=("create_file_artifact", "create_image_artifact"),
    ),
    "default": ToolsetDefinition(
        name="default",
        description="Default Paper Notes agent toolset.",
        includes=("paper_notes", "code_execution", "persistent_memory", "session_search", "todo", "skills", "web_search"),
    ),
}


BUILTIN_TOOL_GROUPS: dict[str, ToolGroupDefinition] = {
    "paper_notes": ToolGroupDefinition(
        name="paper_notes",
        display_name="Paper Notes",
        description=BUILTIN_TOOLSETS["paper_notes"].description,
        default_policy="ask",
        tools=BUILTIN_TOOLSETS["paper_notes"].tools,
        capabilities=(
            "library_search",
            "note_html_read",
            "note_html_write",
            "annotation_read",
            "annotation_write",
            "pdf_text_read",
            "pdf_page_render",
            "pdf_image_extract",
            "vision_analysis",
            "diff_preview",
        ),
    ),
    "persistent_memory": ToolGroupDefinition(
        name="persistent_memory",
        display_name="Persistent Memory",
        description=BUILTIN_TOOLSETS["persistent_memory"].description,
        default_policy="ask",
        tools=BUILTIN_TOOLSETS["persistent_memory"].tools,
        capabilities=("cross_session_memory", "project_memory", "user_profile"),
    ),
    "session_search": ToolGroupDefinition(
        name="session_search",
        display_name="Session Search",
        description=BUILTIN_TOOLSETS["session_search"].description,
        default_policy="auto",
        tools=BUILTIN_TOOLSETS["session_search"].tools,
        capabilities=("transcript_search", "recent_sessions"),
    ),
    "todo": ToolGroupDefinition(
        name="todo",
        display_name="Todo",
        description=BUILTIN_TOOLSETS["todo"].description,
        default_policy="ask",
        tools=BUILTIN_TOOLSETS["todo"].tools,
        capabilities=("session_planning", "compression_reinjection"),
    ),
    "skills": ToolGroupDefinition(
        name="skills",
        display_name="Skills",
        description=BUILTIN_TOOLSETS["skills"].description,
        default_policy="auto",
        tools=BUILTIN_TOOLSETS["skills"].tools,
        capabilities=("skill_discovery", "progressive_disclosure", "supporting_files"),
    ),
    "code_execution": ToolGroupDefinition(
        name="code_execution",
        display_name="Code Execution",
        description=BUILTIN_TOOLSETS["code_execution"].description,
        default_policy="ask",
        tools=BUILTIN_TOOLSETS["code_execution"].tools,
        capabilities=("local_python", "rpc_tools", "light_sandbox"),
    ),
    "web_search": ToolGroupDefinition(
        name="web_search",
        display_name="Custom Web Search",
        description=BUILTIN_TOOLSETS["web_search"].description,
        default_policy="auto",
        tools=BUILTIN_TOOLSETS["web_search"].tools,
        capabilities=("web_search", "web_fetch", "source_attribution", "recency_filter", "domain_filter"),
    ),
    "generated_artifacts": ToolGroupDefinition(
        name="generated_artifacts",
        display_name="Generated Artifacts",
        description=BUILTIN_TOOLSETS["generated_artifacts"].description,
        default_policy="disabled",
        tools=BUILTIN_TOOLSETS["generated_artifacts"].tools,
        capabilities=("image_generation", "file_generation", "artifact_download"),
        metadata={"ui_hidden": True},
    ),
}


@dataclass(frozen=True, slots=True)
class ToolsetResolution:
    enabled_toolsets: tuple[str, ...] = ()
    disabled_toolsets: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = field(default_factory=tuple)
    unknown_toolsets: tuple[str, ...] = ()


def normalize_toolset_names(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_items = value.replace(",", " ").split()
    else:
        raw_items = []
        for item in value:
            if isinstance(item, str):
                raw_items.extend(item.replace(",", " ").split())
            elif item is not None:
                raw_items.append(str(item))
    seen: set[str] = set()
    names: list[str] = []
    for item in raw_items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        names.append(normalized)
        seen.add(normalized)
    return tuple(names)


def resolve_toolsets(
    registry: ToolRegistry,
    *,
    enabled_toolsets: str | Iterable[str] | None = None,
    disabled_toolsets: str | Iterable[str] | None = None,
    default_toolsets: str | Iterable[str] | None = ("default",),
) -> ToolsetResolution:
    enabled = normalize_toolset_names(enabled_toolsets) or normalize_toolset_names(default_toolsets)
    disabled = normalize_toolset_names(disabled_toolsets)
    unknown: list[str] = []
    selected = _resolve_many(registry, enabled, unknown=unknown, seen=set())
    selected.difference_update(_resolve_many(registry, disabled, unknown=unknown, seen=set()))
    available = set(registry.names())
    return ToolsetResolution(
        enabled_toolsets=enabled,
        disabled_toolsets=disabled,
        tool_names=tuple(sorted(selected & available)),
        unknown_toolsets=tuple(dict.fromkeys(unknown)),
    )


def _resolve_many(
    registry: ToolRegistry,
    names: Iterable[str],
    *,
    unknown: list[str],
    seen: set[str],
) -> set[str]:
    tool_names: set[str] = set()
    for name in names:
        tool_names.update(_resolve_one(registry, name, unknown=unknown, seen=seen))
    return tool_names


def _resolve_one(
    registry: ToolRegistry,
    name: str,
    *,
    unknown: list[str],
    seen: set[str],
) -> set[str]:
    normalized = str(name or "").strip()
    if not normalized or normalized in seen:
        return set()
    seen.add(normalized)

    definition = BUILTIN_TOOLSETS.get(normalized)
    if definition is not None:
        resolved = set(definition.tools)
        resolved.update(_resolve_many(registry, definition.includes, unknown=unknown, seen=seen))
        return resolved

    group = registry.get_group(normalized)
    if group is not None:
        return set(group.tools)

    registered_toolset_names = registry.toolsets()
    if normalized in registered_toolset_names:
        return set(registry.tool_names_for_toolset(normalized))

    if registry.get(normalized) is not None:
        return {normalized}

    unknown.append(normalized)
    return set()
