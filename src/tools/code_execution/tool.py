from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

from tools.code_execution.manifest import TOOL_NAME, TOOLSET, TOOL_GROUP
from tools.code_execution.runner import MAX_CODE_BYTES, run_python_code
from tools.registry import ToolDefinition, ToolRegistry


ALLOWED_INNER_TOOL_NAMES = (
    "search_notes",
    "get_note_context",
    "read_paper",
    "review_note",
    "session_search",
    "skills_list",
    "skill_view",
    "web_search",
    "web_fetch",
)

_INNER_TOOL_SUMMARIES = {
    "search_notes": "search_notes(query='', limit=None)",
    "get_note_context": "get_note_context(note_id, query='', include_html=False, html_mode='body', max_paper_matches=4)",
    "read_paper": "read_paper(action, note_id, ...)",
    "review_note": "review_note(action, note_id, heading='', html='', position='append')",
    "session_search": "session_search(query='', role_filter='', limit=5, include_recap=True)",
    "skills_list": "skills_list(category='')",
    "skill_view": "skill_view(name, file_path='')",
    "web_search": "web_search(query, limit=5, allowed_domains=None, recency_days=None, include_summary=True)",
    "web_fetch": "web_fetch(url, max_chars=12000, include_links=False, format='markdown')",
}


def register_code_execution_tool(
    registry: ToolRegistry,
    *,
    available_tool_names_provider: Callable[[], Iterable[str]] | None = None,
    cancel_check_provider: Callable[[], bool] | None = None,
    snapshot_manager_provider: Callable[[], Any] | None = None,
    session_id_provider: Callable[[], str] | None = None,
) -> None:
    registry.register_group(TOOL_GROUP)
    if registry.get(TOOL_NAME) is not None:
        return

    def _handler(args: dict[str, Any]) -> dict[str, Any]:
        code = args.get("code")
        if not isinstance(code, str):
            return _error_result("code must be a string.", "invalid_code")
        if not code.strip():
            return _error_result("code must not be empty.", "empty_code")
        if len(code.encode("utf-8")) > MAX_CODE_BYTES:
            return _error_result(f"code must be at most {MAX_CODE_BYTES} bytes.", "code_too_large")
        visible = available_tool_names_provider() if available_tool_names_provider is not None else None
        allowed_tools = resolve_inner_tool_names(registry, visible_tool_names=visible)
        return run_python_code(
            code,
            registry=registry,
            allowed_tools=set(allowed_tools),
            snapshot_manager=snapshot_manager_provider() if snapshot_manager_provider is not None else None,
            session_id=session_id_provider() if session_id_provider is not None else "",
            cancel_check=cancel_check_provider,
        )

    registry.register(ToolDefinition(
        name=TOOL_NAME,
        description=build_execute_code_description(ALLOWED_INNER_TOOL_NAMES),
        parameters=execute_code_parameters(),
        handler=_handler,
        toolset=TOOLSET,
        read_only=False,
        mutating=True,
        risk="write",
        kind="external",
        result_max_chars=100_000,
        metadata={
            "mode": "local_python_strict",
            "light_sandbox": True,
            "timeout_seconds": 120,
            "max_tool_calls": 25,
            "code_size_bytes": MAX_CODE_BYTES,
        },
        dynamic_schema=execute_code_parameters,
    ))


def execute_code_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to run in a temporary local directory.",
            },
        },
        "required": ["code"],
        "additionalProperties": False,
    }


def build_execute_code_description(available_inner_tools: Iterable[str] | None = None) -> str:
    inner_tools = [name for name in (available_inner_tools or ()) if name in _INNER_TOOL_SUMMARIES]
    if inner_tools:
        tool_text = "; ".join(_INNER_TOOL_SUMMARIES[name] for name in inner_tools)
    else:
        tool_text = "No parent Paper Notes tools are available in this request."
    return (
        "Run Python code in a temporary local directory. This is a light sandbox, not a Docker "
        "or OS-level isolation boundary: do not use it for untrusted code. The child process "
        "gets a fake HOME, scrubbed secret-like environment variables, UTF-8 Python settings, "
        "a 120 second timeout, capped stdout/stderr, and a 25-call limit for parent tool RPC. "
        "Do not use this tool to create generated files/images or write Paper Notes media files; "
        "use dedicated artifact tools when available. If an image artifact tool is not available, "
        "tell the user image generation is unavailable for the current provider/model; do not draw "
        "images with Python, emit SVG/HTML, print base64/data URLs, or write temporary image files. "
        "Suggest switching to the OpenAI API key provider or Codex OAuth provider for image generation. "
        "When available, import parent-tool helpers from paper_notes_tools. Available inner tools: "
        f"{tool_text}."
    )


def resolve_inner_tool_names(
    registry: ToolRegistry,
    *,
    visible_tool_names: Iterable[str] | None = None,
) -> tuple[str, ...]:
    visible = {str(name or "").strip() for name in visible_tool_names or () if str(name or "").strip()}
    use_visibility_filter = visible_tool_names is not None
    allowed: list[str] = []
    for name in ALLOWED_INNER_TOOL_NAMES:
        if use_visibility_filter and name not in visible and not _hidden_inner_tool_enabled(name, visible):
            continue
        definition = registry.get(name)
        if definition is None:
            continue
        if not registry.is_available(name):
            continue
        if _is_allowed_inner_tool_definition(name, definition):
            allowed.append(name)
    return tuple(allowed)


def _hidden_inner_tool_enabled(name: str, visible: set[str]) -> bool:
    return False


def _is_allowed_inner_tool_definition(name: str, definition: ToolDefinition) -> bool:
    if definition.read_only and not definition.mutating and definition.risk == "read":
        return True
    return False


def schema_with_dynamic_description(
    schema: dict[str, Any],
    *,
    registry: ToolRegistry,
    visible_tool_names: Iterable[str],
) -> dict[str, Any]:
    function = schema.get("function") if isinstance(schema, dict) else None
    if not isinstance(function, dict) or function.get("name") != TOOL_NAME:
        return schema
    inner_tools = resolve_inner_tool_names(registry, visible_tool_names=visible_tool_names)
    next_schema = json.loads(json.dumps(schema))
    next_schema["function"]["description"] = build_execute_code_description(inner_tools)
    return next_schema


def _error_result(message: str, code: str) -> dict[str, Any]:
    return {
        "success": False,
        "status": "error",
        "output": "",
        "error": message,
        "tool_calls_made": 0,
        "duration_seconds": 0.0,
        "code": code,
    }


__all__ = [
    "ALLOWED_INNER_TOOL_NAMES",
    "build_execute_code_description",
    "execute_code_parameters",
    "register_code_execution_tool",
    "resolve_inner_tool_names",
    "schema_with_dynamic_description",
]
