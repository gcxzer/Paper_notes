from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from agent_runtime.run_control import AgentRunControl
from agent_runtime.types import AgentEvent
from agent_runtime.types import ToolResult
from tool_safety import ToolApprovalManager
from model_providers.types import ToolCall
from tools.registry import ToolRegistry
from tools.result_storage import ToolResultStore
from tools.types import ToolDefinition, ToolExecutionContext, ToolMiddleware


logger = logging.getLogger(__name__)


class ToolExecutorAdapter:
    """Adapt ToolRegistry dispatch to the agent runtime ToolExecutor protocol."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        snapshot_manager: Any = None,
        approval_manager: ToolApprovalManager | None = None,
        session_id_provider: Callable[[], str] | None = None,
        request_id: str = "",
        write_mode: str = "auto",
        disabled_tools: list[str] | tuple[str, ...] | set[str] | None = None,
        tool_write_modes: dict[str, str] | None = None,
        event_sink: Callable[[AgentEvent], None] | None = None,
        control: AgentRunControl | None = None,
        approval_timeout_seconds: int = 300,
        result_store: ToolResultStore | None = None,
        middlewares: list[ToolMiddleware] | None = None,
        execution_context: ToolExecutionContext | None = None,
    ) -> None:
        self.registry = registry
        self.snapshot_manager = snapshot_manager
        self.approval_manager = approval_manager
        self.session_id_provider = session_id_provider or (lambda: "")
        self.request_id = str(request_id or "").strip()
        self.write_mode = _normalize_write_mode(write_mode)
        self.disabled_tools = {str(name or "").strip() for name in (disabled_tools or []) if str(name or "").strip()}
        self.tool_write_modes = {
            str(name or "").strip(): _normalize_write_mode(mode)
            for name, mode in (tool_write_modes or {}).items()
            if str(name or "").strip()
        }
        self.event_sink = event_sink
        self.control = control
        self.approval_timeout_seconds = max(5, int(approval_timeout_seconds))
        self.result_store = result_store
        self.middlewares = list(middlewares or [])
        self.execution_context = execution_context or ToolExecutionContext()
        self._events: list[AgentEvent] = []
        self._events_lock = threading.Lock()

    def execute(self, tool_call: ToolCall) -> ToolResult:
        arguments = _parse_arguments(tool_call.arguments)
        if arguments is None:
            return ToolResult(
                call_id=tool_call.call_id or tool_call.id,
                name=tool_call.name,
                content=json.dumps({"error": "Tool arguments must be a JSON object."}, ensure_ascii=False),
                is_error=True,
            )

        definition = self.registry.get(tool_call.name)
        if definition is not None:
            arguments = coerce_tool_arguments(definition, arguments)
            effective_write_mode = self._write_mode_for(definition)
            available, availability = self.registry.availability(definition.name)
            if not available:
                code = str(availability.get("code") or "tool_unavailable") if isinstance(availability, dict) else "tool_unavailable"
                message = (
                    str(availability.get("error") or "This tool is not available in this environment.")
                    if isinstance(availability, dict)
                    else "This tool is not available in this environment."
                )
                return ToolResult(
                    call_id=tool_call.call_id or tool_call.id,
                    name=tool_call.name,
                    content=json.dumps({
                        "success": False,
                        "error": message,
                        "code": code,
                        "availability": availability,
                    }, ensure_ascii=False),
                    is_error=True,
                    metadata=self._result_metadata(definition, snapshot=None),
                )
            if definition.name in self.disabled_tools:
                return ToolResult(
                    call_id=tool_call.call_id or tool_call.id,
                    name=tool_call.name,
                    content=json.dumps({
                        "success": False,
                        "error": "This tool is disabled by local tool settings.",
                        "code": "tool_disabled",
                    }, ensure_ascii=False),
                    is_error=True,
                    metadata=self._result_metadata(definition, snapshot=None),
                )
            if definition.mutating and effective_write_mode == "readonly":
                return ToolResult(
                    call_id=tool_call.call_id or tool_call.id,
                    name=tool_call.name,
                    content=json.dumps({
                        "success": False,
                        "error": "Mutating tools are disabled for this run.",
                        "code": "mutating_tools_readonly",
                    }, ensure_ascii=False),
                    is_error=True,
                    metadata=self._result_metadata(definition, snapshot=None),
                )
            if definition.mutating and effective_write_mode in {"block", "halt"}:
                return ToolResult(
                    call_id=tool_call.call_id or tool_call.id,
                    name=tool_call.name,
                    content=json.dumps({
                        "success": False,
                        "error": "Mutating tools are blocked for this run.",
                        "code": "mutating_tools_blocked",
                    }, ensure_ascii=False),
                    is_error=True,
                    metadata=self._result_metadata(definition, snapshot=None),
                )
            if definition.mutating and effective_write_mode == "warn":
                self._record_event(AgentEvent(
                    "tool_warning",
                    f"Running mutating tool {definition.name}.",
                    {
                        "code": "mutating_tool_warn_mode",
                        "tool_name": definition.name,
                        "risk": definition.risk,
                        "write_mode": effective_write_mode,
                    },
                ))
            if self._requires_approval(definition):
                decision = self._request_approval(tool_call, definition, arguments)
                if not decision.get("allowed"):
                    record = decision.get("record") if isinstance(decision.get("record"), dict) else {}
                    return ToolResult(
                        call_id=tool_call.call_id or tool_call.id,
                        name=tool_call.name,
                        content=json.dumps({
                            **approval_denied_result_from_public(record),
                            "success": False,
                        }, ensure_ascii=False),
                        is_error=True,
                        metadata={
                            **self._result_metadata(definition, snapshot=None),
                            "approval": record,
                        },
                    )

        snapshot_handle = self._start_snapshot(tool_call, definition, arguments)
        if definition is not None:
            self._run_before_middlewares(definition, arguments)
        result = self.registry.dispatch(tool_call.name, arguments)
        if definition is not None:
            result = self._run_after_middlewares(definition, arguments, result)
        snapshot = self._finalize_snapshot(snapshot_handle, failed=result.is_error)
        metadata = self._result_metadata(definition, snapshot=snapshot)
        content = self._budgeted_result_content(tool_call, definition, result, metadata)
        return ToolResult(
            call_id=tool_call.call_id or tool_call.id,
            name=result.name,
            content=content,
            is_error=result.is_error,
            metadata=metadata,
        )

    def is_read_only(self, tool_name: str) -> bool:
        definition = self.registry.get(tool_name)
        return bool(definition and definition.read_only)

    def tool_metadata(self, tool_name: str) -> dict[str, Any]:
        definition = self.registry.get(tool_name)
        if definition is None:
            return {}
        return {
            "read_only": definition.read_only,
            "mutating": definition.mutating,
            "risk": definition.risk,
            "kind": definition.kind,
            "version": definition.version,
            "write_mode": self._write_mode_for(definition),
            "disabled": definition.name in self.disabled_tools,
            "availability": dict(definition.availability),
            "approval_scope": definition.approval_scope,
            "supports_snapshot": definition.supports_snapshot,
            "supports_rollback": definition.supports_rollback,
            "metadata": dict(definition.metadata),
        }

    def drain_events(self) -> list[AgentEvent]:
        with self._events_lock:
            events = list(self._events)
            self._events.clear()
            return events

    def enforce_turn_budget(self, tool_messages: list[dict[str, Any]]) -> None:
        if self.result_store is None or not tool_messages:
            return
        self.result_store.enforce_turn_budget(tool_messages, session_id=self.session_id_provider())

    def _requires_approval(self, definition: ToolDefinition) -> bool:
        if not definition.mutating:
            return False
        write_mode = self._write_mode_for(definition)
        if definition.risk == "destructive":
            return write_mode not in {"auto_allowed_destructive"}
        return write_mode == "ask"

    def _write_mode_for(self, definition: ToolDefinition) -> str:
        return self.tool_write_modes.get(definition.name, self.write_mode)

    def _request_approval(
        self,
        tool_call: ToolCall,
        definition: ToolDefinition,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if self.approval_manager is None:
            return {
                "allowed": False,
                "record": {
                    "approvalId": "",
                    "toolName": definition.name,
                    "status": "denied",
                    "message": "Tool approval manager is not configured.",
                },
            }
        decision = self.approval_manager.request_tool_approval(
            session_id=self.session_id_provider(),
            request_id=self.request_id,
            tool_call_id=tool_call.call_id or tool_call.id,
            tool_name=definition.name,
            risk=definition.risk,
            write_mode=self._write_mode_for(definition),
            arguments=arguments,
            timeout_seconds=self.approval_timeout_seconds,
            control=self.control,
            event_callback=self._record_event,
        )
        return {
            "allowed": decision.allowed,
            "action": decision.action,
            "record": decision.record.to_public_dict(),
        }

    def _record_event(self, event: AgentEvent) -> None:
        with self._events_lock:
            self._events.append(event)
        if self.event_sink is None:
            return
        try:
            self.event_sink(event)
        except Exception:
            logger.debug("Tool executor event sink failed for %s", event.type, exc_info=True)

    def _budgeted_result_content(
        self,
        tool_call: ToolCall,
        definition: ToolDefinition | None,
        result: Any,
        metadata: dict[str, Any],
    ) -> str:
        if self.result_store is None:
            return result.content

        raw_content = result.original_content if result.original_content is not None else result.content
        persisted = self.result_store.maybe_persist(
            content=raw_content,
            tool_name=result.name,
            tool_call_id=tool_call.call_id or tool_call.id,
            session_id=self.session_id_provider(),
            threshold=definition.result_max_chars if definition is not None else None,
            reason="result_size",
        )
        if persisted.persisted:
            metadata["tool_result"] = persisted.metadata()
        return persisted.content

    def _start_snapshot(
        self,
        tool_call: ToolCall,
        definition: ToolDefinition | None,
        arguments: dict,
    ) -> object | None:
        if definition is None or not definition.mutating or self.snapshot_manager is None:
            return None
        start = getattr(self.snapshot_manager, "start", None)
        if not callable(start):
            return None
        try:
            return start(
                session_id=self.session_id_provider(),
                tool_call_id=tool_call.call_id or tool_call.id,
                tool_name=definition.name,
                arguments=arguments,
            )
        except Exception:
            logger.debug("Tool snapshot start failed for %s", definition.name, exc_info=True)
            return None

    def _finalize_snapshot(self, snapshot_handle: object | None, *, failed: bool) -> dict[str, Any] | None:
        if snapshot_handle is None or self.snapshot_manager is None:
            return None
        finalize = getattr(self.snapshot_manager, "finalize", None)
        if not callable(finalize):
            return None
        try:
            snapshot = finalize(snapshot_handle, failed=failed)
            return snapshot if isinstance(snapshot, dict) else None
        except Exception:
            logger.debug("Tool snapshot finalize failed.", exc_info=True)
            return None

    def _result_metadata(self, definition: ToolDefinition | None, *, snapshot: dict[str, Any] | None) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if definition is not None:
            metadata.update({
                "read_only": definition.read_only,
                "mutating": definition.mutating,
                "risk": definition.risk,
                "kind": definition.kind,
                "version": definition.version,
                "write_mode": self._write_mode_for(definition),
                "approval_scope": definition.approval_scope,
                "supports_snapshot": definition.supports_snapshot,
                "supports_rollback": definition.supports_rollback,
            })
        if snapshot:
            metadata["snapshot"] = snapshot
            metadata["changed_files"] = snapshot.get("changedFiles", [])
        return metadata

    def _context(self) -> ToolExecutionContext:
        return ToolExecutionContext(
            session_id=self.session_id_provider(),
            request_id=self.request_id,
            provider=self.execution_context.provider,
            model=self.execution_context.model,
            metadata=dict(self.execution_context.metadata),
        )

    def _run_before_middlewares(self, definition: ToolDefinition, arguments: dict[str, Any]) -> None:
        context = self._context()
        for middleware in self.middlewares:
            hook = getattr(middleware, "before_call", None)
            if callable(hook):
                hook(definition=definition, arguments=arguments, context=context)

    def _run_after_middlewares(
        self,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        result: Any,
    ) -> Any:
        context = self._context()
        current = result
        for middleware in self.middlewares:
            after_hook = getattr(middleware, "after_call", None)
            if callable(after_hook):
                after_hook(definition=definition, arguments=arguments, result=current, context=context)
            transform_hook = getattr(middleware, "transform_result", None)
            if callable(transform_hook):
                transformed = transform_hook(definition=definition, arguments=arguments, result=current, context=context)
                if transformed is not None:
                    current = transformed
        return current


def _parse_arguments(raw_arguments: str) -> dict | None:
    if not raw_arguments or not raw_arguments.strip():
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def coerce_tool_arguments(definition: ToolDefinition, arguments: dict) -> dict:
    return _coerce_object(arguments, definition.parameters)


def _coerce_object(value: dict, schema: dict) -> dict:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return value
    coerced = dict(value)
    for key, prop_schema in properties.items():
        if key in coerced and isinstance(prop_schema, dict):
            coerced[key] = _coerce_value(coerced[key], prop_schema)
    return coerced


def _coerce_value(value: object, schema: dict) -> object:
    expected = schema.get("type")
    if isinstance(expected, list):
        expected_types = expected
    else:
        expected_types = [expected]

    if value is None and "null" in expected_types:
        return None
    if "array" in expected_types:
        return _coerce_array(value, schema)
    if "object" in expected_types and isinstance(value, str):
        coerced_object = _coerce_json_object(value)
        if coerced_object is not None:
            return _coerce_object(coerced_object, schema)
    if "object" in expected_types and isinstance(value, dict):
        return _coerce_object(value, schema)
    if "integer" in expected_types:
        coerced_int = _coerce_int(value)
        if coerced_int is not None:
            return coerced_int
    if "number" in expected_types:
        coerced_float = _coerce_float(value)
        if coerced_float is not None:
            return coerced_float
    if "boolean" in expected_types:
        coerced_bool = _coerce_bool(value)
        if coerced_bool is not None:
            return coerced_bool
    return value


def _coerce_array(value: object, schema: dict) -> list | object:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        if isinstance(parsed, list):
            value = parsed
        elif parsed is None:
            return []
        else:
            value = [parsed]
    elif isinstance(value, tuple):
        value = list(value)
    elif not isinstance(value, list):
        value = [value]

    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        return [_coerce_value(item, item_schema) for item in value]
    return value


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped.lstrip("-").isdigit():
            return int(stripped)
    return None


def _normalize_write_mode(value: str) -> str:
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in {"auto", "warn", "ask", "readonly", "block", "halt"} else "auto"


def approval_denied_result_from_public(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "error": str(record.get("message") or "Tool approval was denied."),
        "code": "tool_approval_denied",
        "approvalId": str(record.get("approvalId") or ""),
        "toolName": str(record.get("toolName") or ""),
        "status": str(record.get("status") or "denied"),
    }


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped in {"true", "1", "yes", "y", "on"}:
            return True
        if stripped in {"false", "0", "no", "n", "off"}:
            return False
    return None


def _coerce_json_object(value: str) -> dict | None:
    raw = value.strip()
    if not raw.startswith("{"):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
