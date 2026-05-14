from __future__ import annotations

from typing import Any, Protocol

from tools.registry import ToolDefinition
from tools.persistent_memory.manifest import TOOL_GROUP


PERSISTENT_MEMORY_TOOL_NAME = "persistent_memory"
PERSISTENT_MEMORY_TOOLSET = "persistent_memory"


class PersistentMemoryToolHandler(Protocol):
    def persistent_memory_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


def create_persistent_memory_tool_definition(handler: PersistentMemoryToolHandler) -> ToolDefinition:
    return ToolDefinition(
        name=PERSISTENT_MEMORY_TOOL_NAME,
        description=(
            "Read or update curated persistent memory that survives across sessions. "
            "Use it only for durable facts: user preferences, stable project conventions, "
            "environment details, or recurring corrections. Do not store task progress, "
            "completed-work logs, temporary TODOs, commit SHAs, or facts likely to go stale soon."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "replace", "remove", "read"],
                    "description": "Action to perform. Use read to inspect current entries.",
                },
                "target": {
                    "type": "string",
                    "enum": ["project", "user"],
                    "description": (
                        "project = stable project/environment facts and conventions; "
                        "user = user profile, preferences, communication style."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Entry content for add or replacement content for replace.",
                },
                "old_text": {
                    "type": "string",
                    "description": "Short unique substring identifying the entry to replace or remove.",
                },
            },
            "required": ["action", "target"],
            "additionalProperties": False,
        },
        handler=lambda args: _dispatch_persistent_memory_tool(handler, args),
        toolset=PERSISTENT_MEMORY_TOOLSET,
        read_only=False,
        mutating=True,
        risk="write",
        kind="memory",
        result_max_chars=8_000,
        availability={
            "project": "Local persistent project memory is available.",
            "user": "Local persistent user profile memory is available.",
        },
        metadata={
            "targets": ["project", "user"],
            "durability": "cross_session",
            "group": TOOL_GROUP.name,
        },
    )


def _dispatch_persistent_memory_tool(
    handler: PersistentMemoryToolHandler,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(arguments or {})
    target = str(normalized.get("target") or "project").strip().lower()
    if target in {"project", "project_memory", "persistent_memory"}:
        normalized["target"] = "memory"
    elif target == "user":
        normalized["target"] = "user"
    else:
        normalized["target"] = target

    result = handler.persistent_memory_tool(normalized)
    if isinstance(result, dict) and result.get("target") == "memory":
        return {**result, "target": "project"}
    return result
