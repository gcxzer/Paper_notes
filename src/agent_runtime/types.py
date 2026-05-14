from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agent_runtime.run_control import AgentRunControl
from tool_safety.guardrails import ToolGuardrailConfig
from model_providers.types import TokenUsage, ToolCall


@dataclass(slots=True)
class AgentRunRequest:
    model: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    instructions: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_turns: int = 90
    max_continuation_turns: int = 3
    max_output_tokens: int | None = None
    request_options: dict[str, Any] = field(default_factory=dict)
    control: AgentRunControl | None = None
    tool_guardrails: ToolGuardrailConfig | None = None
    summarize_on_max_turns: bool = True
    budget_warnings_enabled: bool = True
    stream_events_enabled: bool = True


@dataclass(slots=True)
class ToolResult:
    content: str
    call_id: str | None = None
    name: str | None = None
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolExecutor(Protocol):
    def execute(self, tool_call: ToolCall) -> ToolResult | str | dict[str, Any]:
        """Execute one model-requested tool call."""


@dataclass(slots=True)
class AgentEvent:
    type: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


AgentEventSink = Callable[[AgentEvent], None]


@dataclass(slots=True)
class AgentRunResult:
    completed: bool
    final_response: str | None
    messages: list[dict[str, Any]]
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
    turns: int = 0
    pending_tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    error: str | None = None
    cancelled: bool = False
