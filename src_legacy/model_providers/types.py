from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


# The normalized response shape is adapted from Nous Research Hermes Agent's
# transport types (MIT License, Copyright (c) 2025 Nous Research).


@dataclass(slots=True)
class ToolCall:
    id: str | None
    name: str
    arguments: str
    provider_data: dict[str, Any] | None = field(default=None, repr=False)

    @property
    def type(self) -> str:
        return "function"

    @property
    def function(self) -> ToolCall:
        return self

    @property
    def call_id(self) -> str | None:
        return (self.provider_data or {}).get("call_id") or self.id


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class ModelRequest:
    model: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    instructions: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_output_tokens: int | None = None
    request_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: TokenUsage | None = None
    provider_data: dict[str, Any] | None = field(default=None, repr=False)


@dataclass(slots=True)
class ModelStreamEvent:
    type: str
    delta: str = ""
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


ModelStreamEventSink = Callable[[ModelStreamEvent], None]


def build_tool_call(
    id: str | None,
    name: str,
    arguments: Any,
    **provider_fields: Any,
) -> ToolCall:
    arguments_text = json.dumps(arguments) if isinstance(arguments, dict | list) else str(arguments or "{}")
    return ToolCall(
        id=id,
        name=name,
        arguments=arguments_text,
        provider_data=dict(provider_fields) if provider_fields else None,
    )
