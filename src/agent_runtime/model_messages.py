from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any


VALID_API_ROLES = frozenset({"system", "developer", "user", "assistant", "tool", "function"})
MISSING_TOOL_RESULT_CODE = "missing_tool_result_synthetic"


@dataclass(slots=True)
class MessageSanitizationStats:
    removed_invalid_roles: int = 0
    removed_orphaned_tool_results: int = 0
    inserted_missing_tool_results: int = 0
    invalid_roles: list[str] = field(default_factory=list)
    orphaned_tool_call_ids: list[str] = field(default_factory=list)
    missing_tool_call_ids: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.removed_invalid_roles
            or self.removed_orphaned_tool_results
            or self.inserted_missing_tool_results
        )

    def to_event_data(self) -> dict[str, Any]:
        return {
            "removed_invalid_roles": self.removed_invalid_roles,
            "removed_orphaned_tool_results": self.removed_orphaned_tool_results,
            "inserted_missing_tool_results": self.inserted_missing_tool_results,
            "invalid_roles": list(self.invalid_roles),
            "orphaned_tool_call_ids": list(self.orphaned_tool_call_ids),
            "missing_tool_call_ids": list(self.missing_tool_call_ids),
        }


@dataclass(slots=True)
class MessageSanitizationResult:
    messages: list[dict[str, Any]]
    stats: MessageSanitizationStats


def sanitize_model_messages(messages: list[dict[str, Any]]) -> MessageSanitizationResult:
    """Fix role/tool-call invariants before a model request.

    This mirrors the Hermes pre-call sanitizer shape: invalid roles are removed,
    orphaned tool results are dropped, and assistant tool calls with missing
    results get explicit synthetic failure results so the provider never sees a
    broken function_call/function_call_output chain.
    """
    stats = MessageSanitizationStats()
    filtered: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            stats.removed_invalid_roles += 1
            stats.invalid_roles.append(type(message).__name__)
            continue
        role = str(message.get("role") or "")
        if role not in VALID_API_ROLES:
            stats.removed_invalid_roles += 1
            stats.invalid_roles.append(role)
            continue
        filtered.append(copy.deepcopy(message))

    tool_calls_by_id: dict[str, dict[str, Any]] = {}
    tool_call_order: list[str] = []
    for message in filtered:
        if message.get("role") != "assistant":
            continue
        for tool_call in message.get("tool_calls") or []:
            call_id = tool_call_id(tool_call)
            if not call_id:
                continue
            tool_calls_by_id.setdefault(call_id, tool_call)
            tool_call_order.append(call_id)

    result_call_ids = {
        str(message.get("tool_call_id") or "")
        for message in filtered
        if message.get("role") == "tool" and message.get("tool_call_id")
    }
    orphaned_ids = sorted(result_call_ids - set(tool_calls_by_id))
    if orphaned_ids:
        orphaned_set = set(orphaned_ids)
        filtered = [
            message
            for message in filtered
            if not (message.get("role") == "tool" and str(message.get("tool_call_id") or "") in orphaned_set)
        ]
        stats.removed_orphaned_tool_results = len(orphaned_ids)
        stats.orphaned_tool_call_ids = orphaned_ids
        result_call_ids -= orphaned_set

    missing_ids = [call_id for call_id in tool_call_order if call_id not in result_call_ids]
    if not missing_ids:
        return MessageSanitizationResult(messages=filtered, stats=stats)

    missing_set = set(missing_ids)
    patched: list[dict[str, Any]] = []
    inserted: list[str] = []
    for message in filtered:
        patched.append(message)
        if message.get("role") != "assistant":
            continue
        for tool_call in message.get("tool_calls") or []:
            call_id = tool_call_id(tool_call)
            if not call_id or call_id not in missing_set or call_id in inserted:
                continue
            patched.append(synthetic_missing_tool_result(call_id=call_id, tool_name=tool_call_name(tool_call)))
            inserted.append(call_id)

    stats.inserted_missing_tool_results = len(inserted)
    stats.missing_tool_call_ids = inserted
    return MessageSanitizationResult(messages=patched, stats=stats)


def synthetic_missing_tool_result(*, call_id: str, tool_name: str = "") -> dict[str, Any]:
    payload = {
        "success": False,
        "changed": False,
        "error": (
            "This tool result was missing from the local transcript. Do not assume "
            "the tool completed successfully; retry with corrected arguments or explain the blocker."
        ),
        "code": MISSING_TOOL_RESULT_CODE,
        "tool_name": tool_name,
        "tool_call_id": call_id,
    }
    message: dict[str, Any] = {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(payload, ensure_ascii=False),
    }
    if tool_name:
        message["name"] = tool_name
    return message


def tool_call_id(tool_call: Any) -> str:
    if isinstance(tool_call, dict):
        return str(tool_call.get("call_id") or tool_call.get("id") or "")
    return str(getattr(tool_call, "call_id", "") or getattr(tool_call, "id", "") or "")


def tool_call_name(tool_call: Any) -> str:
    if isinstance(tool_call, dict):
        function = tool_call.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or tool_call.get("name") or "")
        return str(tool_call.get("name") or "")
    function = getattr(tool_call, "function", None)
    return str(getattr(function, "name", "") or getattr(tool_call, "name", "") or "")
