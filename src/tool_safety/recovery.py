from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

from model_providers.types import ToolCall


# Tool-call recovery behavior is adapted from Nous Research Hermes Agent's
# run_agent.py (MIT License, Copyright (c) 2025 Nous Research).


INVALID_TOOL_ARGUMENTS_CODE = "invalid_tool_arguments_json"
TRUNCATED_TOOL_ARGUMENTS_CODE = "tool_arguments_truncated"


@dataclass(slots=True)
class InvalidToolArguments:
    call_id: str
    name: str
    error: str
    truncated: bool = False

    def to_event_data(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "error": self.error,
            "truncated": self.truncated,
        }


@dataclass(slots=True)
class ToolCallRecoveryStats:
    normalized_empty_arguments: list[str] = field(default_factory=list)
    deduplicated_call_ids: list[str] = field(default_factory=list)
    invalid_arguments: list[InvalidToolArguments] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.normalized_empty_arguments or self.deduplicated_call_ids or self.invalid_arguments)

    @property
    def has_invalid_arguments(self) -> bool:
        return bool(self.invalid_arguments)

    @property
    def has_truncated_arguments(self) -> bool:
        return any(item.truncated for item in self.invalid_arguments)

    def to_event_data(self) -> dict[str, Any]:
        return {
            "normalized_empty_arguments": list(self.normalized_empty_arguments),
            "deduplicated_call_ids": list(self.deduplicated_call_ids),
            "invalid_arguments": [item.to_event_data() for item in self.invalid_arguments],
        }


@dataclass(slots=True)
class ToolCallRecoveryResult:
    tool_calls: list[ToolCall]
    stats: ToolCallRecoveryStats


def recover_tool_calls(tool_calls: list[ToolCall]) -> ToolCallRecoveryResult:
    """Normalize, validate, and deduplicate model-emitted tool calls.

    This deliberately happens before the executor sees a call. A malformed
    Responses function call is a model/protocol recovery case, not a real local
    tool execution.
    """
    stats = ToolCallRecoveryStats()
    normalized: list[ToolCall] = []

    for tool_call in tool_calls:
        arguments = _arguments_text(tool_call.arguments)
        if not arguments.strip():
            arguments = "{}"
            stats.normalized_empty_arguments.append(_tool_call_id(tool_call))
        parsed, error = _parse_arguments(arguments)
        if error:
            stats.invalid_arguments.append(
                InvalidToolArguments(
                    call_id=_tool_call_id(tool_call),
                    name=tool_call.name,
                    error=error,
                    truncated=_looks_truncated(arguments),
                )
            )
        normalized.append(replace(tool_call, arguments=arguments))

    if stats.invalid_arguments:
        return ToolCallRecoveryResult(tool_calls=normalized, stats=stats)

    deduplicated = _deduplicate_tool_calls(normalized, stats)
    return ToolCallRecoveryResult(tool_calls=deduplicated, stats=stats)


def build_invalid_tool_argument_results(
    tool_calls: list[ToolCall],
    invalid_arguments: list[InvalidToolArguments],
) -> list[dict[str, Any]]:
    invalid_by_call_id = {item.call_id: item for item in invalid_arguments}
    invalid_by_name = {item.name: item for item in invalid_arguments}
    messages: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        call_id = _tool_call_id(tool_call)
        invalid = invalid_by_call_id.get(call_id) or invalid_by_name.get(tool_call.name)
        if invalid is not None:
            payload = {
                "success": False,
                "changed": False,
                "error": (
                    f"Invalid JSON arguments for tool '{tool_call.name}': {invalid.error}. "
                    "Tool arguments must be a JSON object. For tools with no parameters, use {}."
                ),
                "code": INVALID_TOOL_ARGUMENTS_CODE,
                "tool_name": tool_call.name,
                "tool_call_id": call_id,
            }
        else:
            payload = {
                "success": False,
                "changed": False,
                "error": "Skipped because another tool call in this model response had invalid JSON arguments.",
                "code": "tool_call_skipped_invalid_peer_arguments",
                "tool_name": tool_call.name,
                "tool_call_id": call_id,
            }
        messages.append({
            "role": "tool",
            "name": tool_call.name,
            "tool_call_id": call_id,
            "content": json.dumps(payload, ensure_ascii=False),
        })
    return messages


def _arguments_text(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    if arguments is None:
        return ""
    if isinstance(arguments, dict | list):
        return json.dumps(arguments, ensure_ascii=False)
    return str(arguments)


def _parse_arguments(arguments: str) -> tuple[dict[str, Any] | None, str]:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as error:
        return None, str(error)
    if not isinstance(parsed, dict):
        return None, "tool arguments must decode to a JSON object"
    return parsed, ""


def _looks_truncated(arguments: str) -> bool:
    stripped = arguments.rstrip()
    return bool(stripped) and not stripped.endswith(("}", "]"))
 

def _deduplicate_tool_calls(tool_calls: list[ToolCall], stats: ToolCallRecoveryStats) -> list[ToolCall]:
    seen: set[tuple[str, str]] = set()
    unique: list[ToolCall] = []
    for tool_call in tool_calls:
        key = (tool_call.name, tool_call.arguments)
        if key in seen:
            stats.deduplicated_call_ids.append(_tool_call_id(tool_call))
            continue
        seen.add(key)
        unique.append(tool_call)
    return unique


def _tool_call_id(tool_call: ToolCall) -> str:
    return str(tool_call.call_id or tool_call.id or "")
