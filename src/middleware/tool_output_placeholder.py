from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import RemoveMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from middleware.tool_output_common import PLACEHOLDER_PREFIX, is_placeholder_content, saved_output_path, tool_output_text

__all__ = [
    "ToolOutputPlaceholderMiddleware",
    "create_tool_output_placeholder_middleware",
]

DEFAULT_TOOL_OUTPUT_PLACEHOLDER_KEEP_RECENT = 40


@dataclass(slots=True)
class ToolOutputPlaceholderMiddleware(AgentMiddleware):
    keep_recent: int = DEFAULT_TOOL_OUTPUT_PLACEHOLDER_KEEP_RECENT

    def __post_init__(self) -> None:
        self.keep_recent = max(1, int(self.keep_recent))

    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        return self._placeholder_old_outputs(state)

    async def abefore_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        return self._placeholder_old_outputs(state)

    def _placeholder_old_outputs(self, state: dict[str, Any]) -> dict[str, Any] | None:
        messages = list(state.get("messages") or [])
        replaced = placeholder_old_tool_outputs(messages, keep_recent=self.keep_recent)
        if replaced is messages:
            return None
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *replaced]}


def create_tool_output_placeholder_middleware(
    *,
    keep_recent: int = DEFAULT_TOOL_OUTPUT_PLACEHOLDER_KEEP_RECENT,
) -> ToolOutputPlaceholderMiddleware:
    return ToolOutputPlaceholderMiddleware(keep_recent=keep_recent)


def placeholder_old_tool_outputs(messages: list[Any], *, keep_recent: int) -> list[Any]:
    tool_indexes = [index for index, message in enumerate(messages) if isinstance(message, ToolMessage)]
    old_tool_indexes = set(tool_indexes[: max(0, len(tool_indexes) - max(1, int(keep_recent)))])
    if not old_tool_indexes:
        return messages

    changed = False
    replaced: list[Any] = []
    for index, message in enumerate(messages):
        if index in old_tool_indexes and isinstance(message, ToolMessage):
            placeholder = _placeholder_message(message)
            changed = changed or placeholder is not message
            replaced.append(placeholder)
        else:
            replaced.append(message)
    return replaced if changed else messages


def _placeholder_message(message: ToolMessage) -> ToolMessage:
    if is_placeholder_content(message.content):
        return message
    content = _tool_output_placeholder(message)
    if message.content == content:
        return message
    return message.model_copy(update={"content": content})


def _tool_output_placeholder(message: ToolMessage) -> str:
    content = tool_output_text(message.content)
    output_path = saved_output_path(content)
    lines = [
        PLACEHOLDER_PREFIX,
        "This older tool output was omitted to reduce context size.",
        f"Tool call id: {message.tool_call_id}",
        f"Estimated original tokens: {count_tokens_approximately([message])}",
    ]
    if message.name:
        lines.insert(2, f"Tool: {message.name}")
    if output_path:
        lines.append(f"Full output path: {output_path}")
    return "\n".join(lines)

