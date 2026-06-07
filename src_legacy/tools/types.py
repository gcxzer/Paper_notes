"""Shared tool metadata types.

Tool metadata is split into separate concepts so registry, settings, approval,
and runtime guardrails do not blur together:

- `kind` describes what the tool is for:
  `read`, `search`, `write`, `plan`, `memory`, or `external`.
- `risk` describes the safety impact:
  `read` only observes data, `write` changes local state, and `destructive`
  is reserved for delete/large overwrite style operations.
- `read_only` is a strict promise that the handler does not mutate local state;
  read-only tools must use `risk="read"`.
- `mutating` marks tools that can write files or durable state. Mutating tools
  are subject to write modes, approval, snapshots, and rollback metadata.

Runtime loop decisions such as `allow`, `warn`, `block`, and `halt` live in
`tool_safety.guardrails`; those describe a specific call attempt, not the
tool's inherent category.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol


ToolHandler = Callable[[dict[str, Any]], Any]
ToolKind = Literal["read", "search", "write", "plan", "memory", "external"]
ToolRisk = Literal["read", "write", "destructive"]
AvailabilityCheck = Callable[[], bool | dict[str, Any]]
DynamicSchema = Callable[[], dict[str, Any]]
AffectedResources = Callable[[dict[str, Any]], list[str]]


@dataclass(slots=True)
class ToolGroupDefinition:
    name: str
    display_name: str
    description: str
    default_policy: str = "default"
    tools: tuple[str, ...] = ()
    availability: dict[str, Any] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    toolset: str = "default"
    read_only: bool = False
    mutating: bool = False
    risk: ToolRisk = "read"
    result_max_chars: int | None = None
    availability: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    kind: ToolKind = "read"
    version: str = "1"
    availability_check: AvailabilityCheck | None = None
    dynamic_schema: DynamicSchema | None = None
    output_schema: dict[str, Any] | None = None
    affected_resources: AffectedResources | None = None
    approval_scope: str = "tool"
    supports_snapshot: bool = False
    supports_rollback: bool = False

    def __post_init__(self) -> None:
        if self.read_only and self.mutating:
            raise ValueError(f"Tool cannot be both read_only and mutating: {self.name}")
        if self.risk not in {"read", "write", "destructive"}:
            raise ValueError(f"Invalid tool risk for {self.name}: {self.risk}")
        if self.kind not in {"read", "search", "write", "plan", "memory", "external"}:
            raise ValueError(f"Invalid tool kind for {self.name}: {self.kind}")
        if self.mutating and self.kind == "read":
            self.kind = "write"
        if self.read_only and self.risk != "read":
            raise ValueError(f"Read-only tool must use read risk: {self.name}")

    def openai_schema(self) -> dict[str, Any]:
        parameters = self.parameters
        if self.dynamic_schema is not None:
            dynamic = self.dynamic_schema()
            if isinstance(dynamic, dict):
                parameters = dynamic
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


@dataclass(slots=True)
class ToolDispatchResult:
    name: str
    content: str
    is_error: bool = False
    original_content: str | None = None


@dataclass(slots=True)
class ToolExecutionContext:
    session_id: str = ""
    request_id: str = ""
    provider: str = ""
    model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResultEnvelope:
    success: bool
    changed: bool = False
    data: Any = None
    summary: str = ""
    error: str = ""
    code: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    snapshot: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "success": self.success,
            "changed": self.changed,
        }
        if self.data is not None:
            payload["data"] = self.data
        if self.summary:
            payload["summary"] = self.summary
        if self.error:
            payload["error"] = self.error
        if self.code:
            payload["code"] = self.code
        if self.artifacts:
            payload["artifacts"] = self.artifacts
        if self.snapshot:
            payload["snapshot"] = self.snapshot
        if self.metrics:
            payload["metrics"] = self.metrics
        return payload


class ToolMiddleware(Protocol):
    def before_call(
        self,
        *,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> None:
        ...

    def after_call(
        self,
        *,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        result: ToolDispatchResult,
        context: ToolExecutionContext,
    ) -> None:
        ...

    def on_error(
        self,
        *,
        definition: ToolDefinition | None,
        arguments: dict[str, Any],
        error: Exception,
        context: ToolExecutionContext,
    ) -> None:
        ...

    def transform_result(
        self,
        *,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        result: ToolDispatchResult,
        context: ToolExecutionContext,
    ) -> ToolDispatchResult:
        ...
