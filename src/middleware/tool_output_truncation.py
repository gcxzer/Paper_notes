from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.types import Command

from middleware.tool_output_common import safe_output_segment, tool_output_text, truncate_output_text

__all__ = [
    "ToolOutputTruncationMiddleware",
    "create_tool_output_truncation_middleware",
]

DEFAULT_TOOL_OUTPUT_MAX_TOKENS = 8_000
_CHARS_PER_TOKEN = 4


@dataclass(slots=True)
class ToolOutputTruncationMiddleware(AgentMiddleware):
    root_dir: Path
    default_max_tokens: int = DEFAULT_TOOL_OUTPUT_MAX_TOKENS
    tool_limits: dict[str, int] | None = None

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir).expanduser().resolve()
        self.default_max_tokens = max(1, int(self.default_max_tokens))
        self.tool_limits = dict(self.tool_limits or {})

    def wrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        return self._store_if_needed(handler(request), tool_name=_tool_name(request))

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> ToolMessage | Command[Any]:
        return self._store_if_needed(await handler(request), tool_name=_tool_name(request))

    def _store_if_needed(self, result: ToolMessage | Command[Any], *, tool_name: str) -> ToolMessage | Command[Any]:
        if isinstance(result, ToolMessage):
            return self._store_message_if_needed(result, tool_name=tool_name)
        if isinstance(result, Command):
            return self._store_command_messages_if_needed(result, tool_name=tool_name)
        return result

    def _store_message_if_needed(self, message: ToolMessage, *, tool_name: str) -> ToolMessage:
        max_tokens = self._max_tokens_for(tool_name)
        estimated_tokens = count_tokens_approximately([message])
        if estimated_tokens <= max_tokens:
            return message

        full_text = tool_output_text(message.content)
        saved_path = self._write_output(tool_name=tool_name, tool_call_id=message.tool_call_id, text=full_text)
        header = _stored_output_header(
            tool_name=tool_name,
            path=saved_path,
            estimated_tokens=estimated_tokens,
            max_tokens=max_tokens,
        )
        preview = truncate_output_text(full_text, max_tokens=max_tokens, chars_per_token=_CHARS_PER_TOKEN)
        content = f"{header}{preview}"
        return message.model_copy(update={"content": content})

    def _store_command_messages_if_needed(self, command: Command[Any], *, tool_name: str) -> Command[Any]:
        update = command.update
        if not isinstance(update, dict):
            return command
        messages = update.get("messages")
        if not isinstance(messages, list):
            return command

        changed = False
        stored_messages: list[Any] = []
        for message in messages:
            if isinstance(message, ToolMessage):
                stored = self._store_message_if_needed(message, tool_name=tool_name)
                changed = changed or stored is not message
                stored_messages.append(stored)
            else:
                stored_messages.append(message)
        if not changed:
            return command
        return replace(command, update={**update, "messages": stored_messages})

    def _max_tokens_for(self, tool_name: str) -> int:
        limit = (self.tool_limits or {}).get(tool_name, self.default_max_tokens)
        try:
            return max(1, int(limit))
        except (TypeError, ValueError):
            return self.default_max_tokens

    def _write_output(self, *, tool_name: str, tool_call_id: str, text: str) -> Path:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{timestamp}-{safe_output_segment(tool_name)}-{safe_output_segment(tool_call_id)}-{uuid.uuid4().hex[:8]}.txt"
        path = self.root_dir / filename
        path.write_text(text, encoding="utf-8")
        return path


def create_tool_output_truncation_middleware(
    *,
    root_dir: str | Path,
    default_max_tokens: int = DEFAULT_TOOL_OUTPUT_MAX_TOKENS,
    tool_limits: dict[str, int] | None = None,
) -> ToolOutputTruncationMiddleware:
    return ToolOutputTruncationMiddleware(
        root_dir=Path(root_dir),
        default_max_tokens=default_max_tokens,
        tool_limits=tool_limits,
    )


def _tool_name(request: Any) -> str:
    tool = getattr(request, "tool", None)
    name = getattr(tool, "name", "") if tool is not None else ""
    if name:
        return str(name)
    tool_call = getattr(request, "tool_call", None)
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "tool")
    return "tool"


def _stored_output_header(
    *,
    tool_name: str,
    path: Path,
    estimated_tokens: int,
    max_tokens: int,
) -> str:
    return (
        f"Tool output for `{tool_name}` exceeded the configured limit and was saved to disk.\n"
        f"Full output path: {path}\n"
        f"Estimated tokens: {estimated_tokens}; configured limit: {max_tokens}.\n\n"
        "Beginning of output:\n"
    )
