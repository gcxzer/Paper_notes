from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.model_messages import MessageSanitizationResult, sanitize_model_messages
from tool_safety.guardrails import (
    ToolCallGuardrailController,
    ToolGuardrailDecision,
    append_toolguard_guidance,
    toolguard_synthetic_result,
)
from tool_safety.recovery import (
    ToolCallRecoveryResult,
    build_invalid_tool_argument_results,
    recover_tool_calls,
)
from agent_runtime.types import AgentEvent, AgentEventSink, AgentRunRequest, AgentRunResult, ToolExecutor, ToolResult
from model_providers.base import ModelProvider
from model_providers.types import ModelRequest, ModelResponse, ModelStreamEvent, TokenUsage, ToolCall


logger = logging.getLogger(__name__)

_BUDGET_WARNING_THRESHOLDS = (
    ("notice", 0.70),
    ("urgent", 0.85),
    ("final", 0.90),
)
_BUDGET_WARNING_RANK = {"notice": 1, "urgent": 2, "final": 3}
_MAX_TURNS_SUMMARY_PROMPT = (
    "You reached the maximum tool-calling iterations. Do not call tools. "
    "Summarize what was completed, what changed, and what remains."
)
_MAX_TURNS_SUMMARY_FALLBACK = (
    "I reached the maximum tool-calling iterations and could not generate a final summary."
)


@dataclass(slots=True)
class _LoopState:
    messages: list[dict[str, Any]]
    max_turns: int
    max_continuation_turns: int
    events: list[AgentEvent] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    final_response: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    continuation_count: int = 0
    invalid_tool_argument_retries: int = 0
    post_tool_empty_retried: bool = False
    last_content_with_tools: str | None = None
    last_content_tools_all_housekeeping: bool = False
    last_budget_warning_level: str = ""

    @classmethod
    def from_request(cls, request: AgentRunRequest) -> "_LoopState":
        return cls(
            messages=copy.deepcopy(request.messages),
            max_turns=max(1, request.max_turns),
            max_continuation_turns=max(0, request.max_continuation_turns),
        )


@dataclass(slots=True)
class _TurnResult:
    action: str
    response: ModelResponse | None = None
    result: AgentRunResult | None = None


def run_agent_loop(
    model_provider: ModelProvider,
    request: AgentRunRequest,
    *,
    tool_executor: ToolExecutor | None = None,
    event_sink: AgentEventSink | None = None,
) -> AgentRunResult:
    state = _LoopState.from_request(request)
    tool_guardrails = ToolCallGuardrailController(request.tool_guardrails) if tool_executor is not None else None

    for turn_index in range(state.max_turns):
        turn_start_messages = copy.deepcopy(state.messages)
        if _is_cancelled(request):
            return _finish_cancelled(request, state, event_sink, turn_index, turn_start_messages)

        model_turn = _call_model_turn(
            model_provider,
            request,
            state,
            turn_index,
            turn_start_messages,
            event_sink,
        )
        if model_turn.result is not None:
            return model_turn.result
        if model_turn.response is None:
            continue

        turn = _handle_model_response(
            request,
            state,
            model_turn.response,
            turn_index,
            turn_start_messages,
            event_sink,
        )
        if turn.result is not None:
            return turn.result
        if turn.action == "continue_loop":
            continue
        if turn.action != "execute_tools" or turn.response is None:
            continue

        if tool_executor is None:
            return _finish_pending_tools(state, turn.response.tool_calls, turn_index + 1, event_sink)

        tool_turn = _execute_tool_turn(
            request,
            state,
            turn.response.tool_calls,
            tool_executor,
            tool_guardrails,
            turn_index,
            turn_start_messages,
            event_sink,
        )
        if tool_turn.result is not None:
            return tool_turn.result

    return _finish_max_turns(model_provider, request, state, event_sink)


def _call_model_turn(
    model_provider: ModelProvider,
    request: AgentRunRequest,
    state: _LoopState,
    turn_index: int,
    turn_start_messages: list[dict[str, Any]],
    event_sink: AgentEventSink | None,
) -> _TurnResult:
    sanitized = sanitize_model_messages(state.messages)
    if sanitized.stats.changed:
        _record_event(
            state.events,
            _model_message_sanitized_event(sanitized),
            event_sink,
        )

    model_messages = sanitized.messages
    if request.budget_warnings_enabled:
        model_messages = _messages_with_budget_warning(
            sanitized.messages,
            state,
            turn_index,
            event_sink,
        )
    model_messages = _with_ephemeral_messages(model_messages, request.request_options)

    model_request = ModelRequest(
        model=request.model,
        messages=model_messages,
        instructions=request.instructions,
        tools=request.tools,
        max_output_tokens=request.max_output_tokens,
        request_options=request.request_options,
    )
    _record_event(
        state.events,
        AgentEvent("model_request", "Calling model provider.", {"turn": turn_index + 1}),
        event_sink,
    )
    if _is_cancelled(request):
        return _TurnResult(
            "return_result",
            result=_finish_cancelled(request, state, event_sink, turn_index, turn_start_messages),
        )

    streamed_work_events: list[AgentEvent] = []
    response = _generate_model_response(
        model_provider,
        model_request,
        request,
        turn_index,
        event_sink,
        streamed_work_events=streamed_work_events,
    )
    _accumulate_usage(state.usage, response.usage)
    state.artifacts.extend(response.artifacts)
    for work_event in _reasoning_trace_events_from_response(response, turn_index + 1):
        _record_event(state.events, work_event, event_sink)
    for work_event in _work_trace_events_from_response(response, turn_index + 1):
        _record_event(state.events, work_event, event_sink)
    _record_event(state.events, _model_response_event(response, turn_index + 1), event_sink)
    if _is_cancelled(request):
        _record_cancelled_stream_work_events(state.events, streamed_work_events)
        return _TurnResult(
            "return_result",
            result=_finish_cancelled(request, state, event_sink, turn_index + 1, turn_start_messages),
        )

    return _TurnResult("handle_response", response=response)


def _generate_model_response(
    model_provider: ModelProvider,
    model_request: ModelRequest,
    request: AgentRunRequest,
    turn_index: int,
    event_sink: AgentEventSink | None,
    *,
    streamed_work_events: list[AgentEvent] | None = None,
) -> ModelResponse:
    stream_generate = getattr(model_provider, "stream_generate", None)
    if not request.stream_events_enabled or not callable(stream_generate):
        return model_provider.generate(model_request)

    def on_stream_event(event: ModelStreamEvent) -> None:
        data = dict(event.data)
        data.update({
            "turn": turn_index + 1,
        })
        if event_sink is not None:
            if event.type == "text_delta":
                data.update({"delta": event.delta, "text": event.text})
                event_sink(AgentEvent("model_delta", "Receiving model response.", data))
            elif event.type == "reasoning_summary_delta":
                data.update({"delta": event.delta, "text": event.text, "trace_type": "summary"})
                agent_event = AgentEvent("work_trace_delta", event.delta or event.text, data)
                if streamed_work_events is not None:
                    streamed_work_events.append(agent_event)
                event_sink(agent_event)
            elif event.type == "reasoning_summary_done":
                data.update({"text": event.text, "trace_type": "summary", "source": "provider"})
                agent_event = AgentEvent("work_trace_item", event.text, data)
                if streamed_work_events is not None:
                    streamed_work_events.append(agent_event)
                event_sink(agent_event)
            elif event.type == "assistant_commentary_delta":
                data.update({"delta": event.delta, "text": event.text, "trace_type": "commentary"})
                agent_event = AgentEvent("work_trace_delta", event.delta or event.text, data)
                if streamed_work_events is not None:
                    streamed_work_events.append(agent_event)
                event_sink(agent_event)
            elif event.type == "assistant_commentary_done":
                data.update({"text": event.text, "trace_type": "commentary", "source": "provider"})
                agent_event = AgentEvent("work_trace_item", event.text, data)
                if streamed_work_events is not None:
                    streamed_work_events.append(agent_event)
                event_sink(agent_event)

    return stream_generate(model_request, event_sink=on_stream_event)


def _messages_with_budget_warning(
    messages: list[dict[str, Any]],
    state: _LoopState,
    turn_index: int,
    event_sink: AgentEventSink | None,
) -> list[dict[str, Any]]:
    level = _iteration_budget_warning_level(turn_index, state.max_turns)
    if not level:
        return messages
    previous_rank = _BUDGET_WARNING_RANK.get(state.last_budget_warning_level, 0)
    if _BUDGET_WARNING_RANK[level] <= previous_rank:
        return messages

    state.last_budget_warning_level = level
    warning = _iteration_budget_warning(level, turn_index, state.max_turns)
    _record_event(
        state.events,
        AgentEvent("iteration_budget_warning", warning["message"], warning),
        event_sink,
    )
    return _inject_iteration_budget_warning(copy.deepcopy(messages), warning)


def _iteration_budget_warning_level(turn_index: int, max_turns: int) -> str:
    if max_turns <= 1:
        return ""
    used = max(0, turn_index)
    ratio = used / max_turns
    level = ""
    for candidate, threshold in _BUDGET_WARNING_THRESHOLDS:
        if ratio >= threshold:
            level = candidate
    return level


def _iteration_budget_warning(level: str, used: int, max_turns: int) -> dict[str, Any]:
    remaining = max(max_turns - used, 0)
    message = (
        f"Iteration budget {level}: {used}/{max_turns} model calls used, "
        f"{remaining} remaining. Prioritize finishing the user's request and avoid unnecessary tools."
    )
    return {
        "level": level,
        "used": used,
        "max": max_turns,
        "remaining": remaining,
        "message": message,
    }


def _inject_iteration_budget_warning(
    messages: list[dict[str, Any]],
    warning: dict[str, Any],
) -> list[dict[str, Any]]:
    if messages and messages[-1].get("role") == "tool":
        message = messages[-1]
        content = str(message.get("content") or "")
        try:
            payload = json.loads(content) if content else {}
        except json.JSONDecodeError:
            message["content"] = f"{content}\n\n[{warning['message']}]" if content else warning["message"]
            return messages
        if isinstance(payload, dict):
            payload["_budget_warning"] = {
                "level": warning["level"],
                "used": warning["used"],
                "max": warning["max"],
                "remaining": warning["remaining"],
                "message": warning["message"],
            }
            message["content"] = json.dumps(payload, ensure_ascii=False)
            return messages
        message["content"] = f"{content}\n\n[{warning['message']}]" if content else warning["message"]
        return messages

    messages.append({
        "role": "developer",
        "content": warning["message"],
        "_iteration_budget_warning": True,
    })
    return messages


def _handle_model_response(
    request: AgentRunRequest,
    state: _LoopState,
    response: ModelResponse,
    turn_index: int,
    turn_start_messages: list[dict[str, Any]],
    event_sink: AgentEventSink | None,
) -> _TurnResult:
    if response.tool_calls:
        prepared = _prepare_tool_calls(state, response, turn_index, event_sink)
        if prepared.result is not None or prepared.action == "continue_loop":
            return prepared
        if prepared.response is not None:
            response = prepared.response

    if response.content and response.finish_reason != "incomplete":
        state.final_response = response.content

    assistant_message = _assistant_message_from_response(response)
    if assistant_message is not None:
        if _is_cancelled(request):
            return _TurnResult(
                "return_result",
                result=_finish_cancelled(
                    request,
                    state,
                    event_sink,
                    turn_index + 1,
                    turn_start_messages,
                ),
            )
        state.messages.append(assistant_message)

    if not response.tool_calls and response.finish_reason == "incomplete":
        return _handle_incomplete_response(state, turn_index, event_sink)

    if not response.tool_calls:
        return _handle_no_tool_response(request, state, response, turn_index, turn_start_messages, event_sink)

    state.continuation_count = 0
    return _TurnResult("execute_tools", response=response)


def _prepare_tool_calls(
    state: _LoopState,
    response: ModelResponse,
    turn_index: int,
    event_sink: AgentEventSink | None,
) -> _TurnResult:
    recovery = recover_tool_calls(response.tool_calls)
    if recovery.stats.has_invalid_arguments:
        state.invalid_tool_argument_retries += 1
        _record_event(
            state.events,
            _tool_call_recovery_event(
                recovery,
                retry=state.invalid_tool_argument_retries,
                max_retries=3,
            ),
            event_sink,
        )
        if recovery.stats.has_truncated_arguments:
            return _TurnResult(
                "return_result",
                result=_finish_error(state, turn_index + 1, "tool_arguments_truncated"),
            )
        if state.invalid_tool_argument_retries < 3:
            return _TurnResult("continue_loop")

        state.invalid_tool_argument_retries = 0
        response.tool_calls = recovery.tool_calls
        assistant_message = _assistant_message_from_response(response)
        if assistant_message is not None:
            state.messages.append(assistant_message)
        recovery_messages = build_invalid_tool_argument_results(
            recovery.tool_calls,
            recovery.stats.invalid_arguments,
        )
        state.messages.extend(recovery_messages)
        _record_event(
            state.events,
            AgentEvent(
                "tool_call_recovery_injected",
                "Injected tool error results so the model can repair invalid tool arguments.",
                {
                    "tool_result_count": len(recovery_messages),
                    "invalid_arguments": [
                        item.to_event_data() for item in recovery.stats.invalid_arguments
                    ],
                },
            ),
            event_sink,
        )
        return _TurnResult("continue_loop")

    state.invalid_tool_argument_retries = 0
    response.tool_calls = recovery.tool_calls
    if recovery.stats.changed:
        _record_event(state.events, _tool_call_recovery_event(recovery), event_sink)
    if response.content and response.content.strip():
        state.last_content_with_tools = response.content
        state.last_content_tools_all_housekeeping = _all_tool_calls_housekeeping(response.tool_calls)
    return _TurnResult("handle_response", response=response)


def _handle_incomplete_response(
    state: _LoopState,
    turn_index: int,
    event_sink: AgentEventSink | None,
) -> _TurnResult:
    state.continuation_count += 1
    if state.continuation_count > state.max_continuation_turns or turn_index + 1 >= state.max_turns:
        _record_event(
            state.events,
            AgentEvent(
                "model_continuation_exhausted",
                "Model response stayed incomplete after continuation attempts.",
                {
                    "turns": turn_index + 1,
                    "continuations": state.continuation_count,
                    "max_continuation_turns": state.max_continuation_turns,
                },
            ),
            event_sink,
        )
        return _TurnResult(
            "return_result",
            result=_finish_error(state, turn_index + 1, "model_incomplete_continuation_exhausted"),
        )
    _record_event(
        state.events,
        AgentEvent(
            "model_continuation",
            "Model response was incomplete; continuing the Responses conversation.",
            {
                "turn": turn_index + 1,
                "continuation": state.continuation_count,
                "max_continuation_turns": state.max_continuation_turns,
            },
        ),
        event_sink,
    )
    return _TurnResult("continue_loop")


def _handle_no_tool_response(
    request: AgentRunRequest,
    state: _LoopState,
    response: ModelResponse,
    turn_index: int,
    turn_start_messages: list[dict[str, Any]],
    event_sink: AgentEventSink | None,
) -> _TurnResult:
    if _should_recover_empty_after_tools(response, state.messages):
        return _handle_empty_after_tools(state, response, turn_index, event_sink)
    if _is_cancelled(request):
        return _TurnResult(
            "return_result",
            result=_finish_cancelled(request, state, event_sink, turn_index + 1, turn_start_messages),
        )
    return _TurnResult(
        "return_result",
        result=_finish_completed(state, turn_index + 1, event_sink),
    )


def _handle_empty_after_tools(
    state: _LoopState,
    response: ModelResponse,
    turn_index: int,
    event_sink: AgentEventSink | None,
) -> _TurnResult:
    if state.last_content_with_tools and state.last_content_tools_all_housekeeping:
        state.final_response = state.last_content_with_tools.strip()
        _record_event(
            state.events,
            AgentEvent(
                "model_empty_after_tool_fallback",
                "Model returned empty after housekeeping tools; using the prior assistant content.",
                {"tool_turn": True},
            ),
            event_sink,
        )
        return _TurnResult(
            "return_result",
            result=_finish_completed(state, turn_index + 1, event_sink),
        )

    if not state.post_tool_empty_retried:
        state.post_tool_empty_retried = True
        _append_empty_tool_recovery_nudge(state.messages, response)
        _record_event(
            state.events,
            AgentEvent(
                "model_empty_after_tool_nudge",
                "Model returned empty after tool results; nudging it to continue.",
                {"turn": turn_index + 1},
            ),
            event_sink,
        )
        return _TurnResult("continue_loop")

    _record_event(
        state.events,
        AgentEvent(
            "model_empty_after_tool_exhausted",
            "Model stayed empty after tool results and one recovery nudge.",
            {"turn": turn_index + 1},
        ),
        event_sink,
    )
    return _TurnResult(
        "return_result",
        result=_finish_error(state, turn_index + 1, "model_empty_after_tool_results"),
    )


def _execute_tool_turn(
    request: AgentRunRequest,
    state: _LoopState,
    tool_calls: list[ToolCall],
    tool_executor: ToolExecutor,
    tool_guardrails: ToolCallGuardrailController | None,
    turn_index: int,
    turn_start_messages: list[dict[str, Any]],
    event_sink: AgentEventSink | None,
) -> _TurnResult:
    turn_tool_messages: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        tool_step = _execute_one_tool_call(
            request,
            state,
            tool_call,
            tool_executor,
            tool_guardrails,
            turn_index,
            turn_start_messages,
            turn_tool_messages,
            event_sink,
        )
        if tool_step.result is not None:
            return tool_step

    _enforce_turn_tool_budget(tool_executor, turn_tool_messages)
    state.post_tool_empty_retried = False
    return _TurnResult("continue_loop")


def _execute_one_tool_call(
    request: AgentRunRequest,
    state: _LoopState,
    tool_call: ToolCall,
    tool_executor: ToolExecutor,
    tool_guardrails: ToolCallGuardrailController | None,
    turn_index: int,
    turn_start_messages: list[dict[str, Any]],
    turn_tool_messages: list[dict[str, Any]],
    event_sink: AgentEventSink | None,
) -> _TurnResult:
    tool_args = _tool_arguments_for_guardrail(tool_call)
    read_only = _tool_is_read_only(tool_executor, tool_call.name)
    tool_metadata = _tool_metadata(tool_executor, tool_call.name)
    before_decision = (
        tool_guardrails.before_call(tool_call.name, tool_args, read_only=read_only)
        if tool_guardrails is not None
        else ToolGuardrailDecision(tool_name=tool_call.name)
    )
    if before_decision.blocks_execution:
        return _handle_tool_blocked(
            state,
            tool_call,
            before_decision,
            turn_index,
            turn_tool_messages,
            event_sink,
        )

    cancelled = _tool_preflight_cancelled(request, state, turn_index, turn_start_messages, event_sink)
    if cancelled is not None:
        return cancelled

    _record_event(
        state.events,
        AgentEvent(
            "tool_call",
            f"Executing tool: {tool_call.name}",
            _tool_call_data(
                tool_call,
                read_only=read_only,
                tool_metadata=tool_metadata,
            ),
        ),
        event_sink,
    )
    if _should_warn_for_mutating_tool(tool_metadata):
        _record_mutating_tool_warning(state, tool_call, tool_metadata, event_sink)

    cancelled = _tool_preflight_cancelled(request, state, turn_index, turn_start_messages, event_sink)
    if cancelled is not None:
        return cancelled

    tool_result = _execute_tool(tool_executor, tool_call)
    _append_executor_events(state.events, tool_executor)
    after_decision = (
        tool_guardrails.after_call(
            tool_call.name,
            tool_args,
            tool_result.content,
            failed=tool_result.is_error,
            read_only=read_only,
        )
        if tool_guardrails is not None
        else ToolGuardrailDecision(tool_name=tool_call.name)
    )
    if after_decision.action in {"warn", "halt"}:
        tool_result = ToolResult(
            call_id=tool_result.call_id,
            name=tool_result.name,
            content=append_toolguard_guidance(tool_result.content, after_decision),
            is_error=tool_result.is_error,
            metadata=tool_result.metadata,
        )

    cancelled = _tool_preflight_cancelled(request, state, turn_index, turn_start_messages, event_sink)
    if cancelled is not None:
        return cancelled

    tool_message = _tool_message_from_result(tool_call, tool_result)
    state.messages.append(tool_message)
    turn_tool_messages.append(tool_message)
    _extend_artifacts(state.artifacts, _artifacts_from_tool_result(tool_result))
    event_type = "tool_error" if tool_result.is_error else "tool_result"
    _record_event(
        state.events,
        AgentEvent(event_type, f"Tool completed: {tool_call.name}", _tool_result_data(tool_result)),
        event_sink,
    )
    if after_decision.action == "warn":
        _record_event(state.events, _tool_guardrail_event(after_decision, "tool_warning"), event_sink)
    if after_decision.halts_run:
        _record_event(state.events, _tool_guardrail_event(after_decision, "tool_halted"), event_sink)
        return _TurnResult(
            "return_result",
            result=_tool_guardrail_halted_result(
                messages=state.messages,
                events=state.events,
                turns=turn_index + 1,
                final_response=state.final_response,
                decision=after_decision,
                usage=_usage_or_none(state.usage),
            ),
        )
    return _TurnResult("continue_loop")


def _handle_tool_blocked(
    state: _LoopState,
    tool_call: ToolCall,
    decision: ToolGuardrailDecision,
    turn_index: int,
    turn_tool_messages: list[dict[str, Any]],
    event_sink: AgentEventSink | None,
) -> _TurnResult:
    synthetic_result = ToolResult(
        call_id=tool_call.call_id or tool_call.id,
        name=tool_call.name,
        content=toolguard_synthetic_result(decision),
        is_error=True,
    )
    tool_message = _tool_message_from_result(tool_call, synthetic_result)
    state.messages.append(tool_message)
    turn_tool_messages.append(tool_message)
    _record_event(
        state.events,
        _tool_guardrail_event(decision, "tool_halted" if decision.halts_run else "tool_blocked"),
        event_sink,
    )
    if decision.halts_run:
        return _TurnResult(
            "return_result",
            result=_tool_guardrail_halted_result(
                messages=state.messages,
                events=state.events,
                turns=turn_index + 1,
                final_response=state.final_response,
                decision=decision,
                usage=_usage_or_none(state.usage),
            ),
        )
    return _TurnResult("continue_loop")


def _tool_preflight_cancelled(
    request: AgentRunRequest,
    state: _LoopState,
    turn_index: int,
    turn_start_messages: list[dict[str, Any]],
    event_sink: AgentEventSink | None,
) -> _TurnResult | None:
    if not _is_cancelled(request):
        return None
    return _TurnResult(
        "return_result",
        result=_finish_cancelled(request, state, event_sink, turn_index + 1, turn_start_messages),
    )


def _record_mutating_tool_warning(
    state: _LoopState,
    tool_call: ToolCall,
    tool_metadata: dict[str, Any],
    event_sink: AgentEventSink | None,
) -> None:
    _record_event(
        state.events,
        AgentEvent(
            "tool_warning",
            f"Mutating tool allowed with warning: {tool_call.name}",
            {
                "action": "warn",
                "code": "mutating_tool_warn_mode",
                "tool_name": tool_call.name,
                "risk": tool_metadata.get("risk") or "write",
                "write_mode": tool_metadata.get("write_mode") or "warn",
            },
        ),
        event_sink,
    )


def _finish_completed(
    state: _LoopState,
    turns: int,
    event_sink: AgentEventSink | None,
) -> AgentRunResult:
    _record_event(
        state.events,
        AgentEvent("completed", "Agent run completed.", {"turns": turns}),
        event_sink,
    )
    return AgentRunResult(
        completed=True,
        final_response=state.final_response,
        messages=state.messages,
        artifacts=state.artifacts,
        events=state.events,
        turns=turns,
        usage=_usage_or_none(state.usage),
    )


def _finish_pending_tools(
    state: _LoopState,
    tool_calls: list[ToolCall],
    turns: int,
    event_sink: AgentEventSink | None,
) -> AgentRunResult:
    _record_event(
        state.events,
        AgentEvent(
            "tool_calls_pending",
            "Model requested tools, but no tool executor is configured.",
            {"tool_calls": [_tool_call_data(tool_call) for tool_call in tool_calls]},
        ),
        event_sink,
    )
    return AgentRunResult(
        completed=False,
        final_response=state.final_response,
        messages=state.messages,
        artifacts=state.artifacts,
        events=state.events,
        turns=turns,
        pending_tool_calls=tool_calls,
        usage=_usage_or_none(state.usage),
        error="tool_executor_missing",
    )


def _finish_error(state: _LoopState, turns: int, error: str) -> AgentRunResult:
    return AgentRunResult(
        completed=False,
        final_response=state.final_response,
        messages=state.messages,
        artifacts=state.artifacts,
        events=state.events,
        turns=turns,
        usage=_usage_or_none(state.usage),
        error=error,
    )


def _finish_cancelled(
    request: AgentRunRequest,
    state: _LoopState,
    event_sink: AgentEventSink | None,
    turns: int,
    messages: list[dict[str, Any]],
) -> AgentRunResult:
    has_work_trace = _has_work_trace_events(state.events)
    result_messages = state.messages if has_work_trace and len(state.messages) > len(messages) else messages
    if has_work_trace and not any(message.get("role") == "assistant" for message in result_messages):
        result_messages = [*result_messages, {"role": "assistant", "content": ""}]
    return _cancelled_result(
        request,
        messages=result_messages,
        events=state.events,
        event_sink=event_sink,
        turns=turns,
        final_response=state.final_response,
        usage=_usage_or_none(state.usage),
    )


def _finish_max_turns(
    model_provider: ModelProvider,
    request: AgentRunRequest,
    state: _LoopState,
    event_sink: AgentEventSink | None,
) -> AgentRunResult:
    _record_event(
        state.events,
        AgentEvent("halted", "Maximum agent turns reached.", {"max_turns": state.max_turns}),
        event_sink,
    )
    if request.summarize_on_max_turns and not _is_cancelled(request):
        _summarize_max_turns(model_provider, request, state, event_sink)
    return AgentRunResult(
        completed=False,
        final_response=state.final_response,
        messages=state.messages,
        artifacts=state.artifacts,
        events=state.events,
        turns=state.max_turns,
        usage=_usage_or_none(state.usage),
        error="max_turns_exceeded",
    )


def _summarize_max_turns(
    model_provider: ModelProvider,
    request: AgentRunRequest,
    state: _LoopState,
    event_sink: AgentEventSink | None,
) -> None:
    try:
        sanitized = sanitize_model_messages(state.messages)
        summary_messages = _with_ephemeral_messages(copy.deepcopy(sanitized.messages), request.request_options)
        summary_messages.append({
            "role": "user",
            "content": _MAX_TURNS_SUMMARY_PROMPT,
        })
        model_request = ModelRequest(
            model=request.model,
            messages=summary_messages,
            instructions=request.instructions,
            tools=[],
            max_output_tokens=request.max_output_tokens,
            request_options=request.request_options,
        )
        _record_event(
            state.events,
            AgentEvent(
                "max_turns_summary_request",
                "Calling model provider for a final no-tool summary.",
                {"turns": state.max_turns},
            ),
            event_sink,
        )
        response = model_provider.generate(model_request)
    except Exception as error:
        state.final_response = _MAX_TURNS_SUMMARY_FALLBACK
        _append_max_turns_summary_message(state, _MAX_TURNS_SUMMARY_FALLBACK, finish_reason="error")
        _record_event(
            state.events,
            AgentEvent(
                "max_turns_summary_failed",
                "Could not generate a final summary after the agent reached its iteration budget.",
                {"error": str(error)},
            ),
            event_sink,
        )
        return

    _accumulate_usage(state.usage, response.usage)
    state.artifacts.extend(response.artifacts)
    _record_event(state.events, _model_response_event(response, state.max_turns + 1), event_sink)
    content = (response.content or "").strip()
    if not content:
        state.final_response = _MAX_TURNS_SUMMARY_FALLBACK
        _append_max_turns_summary_message(state, _MAX_TURNS_SUMMARY_FALLBACK, finish_reason="empty")
        _record_event(
            state.events,
            AgentEvent(
                "max_turns_summary_empty",
                "Final no-tool summary response was empty.",
                {"turns": state.max_turns},
            ),
            event_sink,
        )
        return

    state.final_response = content
    _append_max_turns_summary_message(state, content, finish_reason=response.finish_reason)


def _append_max_turns_summary_message(
    state: _LoopState,
    content: str,
    *,
    finish_reason: str,
) -> None:
    state.messages.append({
        "role": "assistant",
        "content": content,
        "finish_reason": finish_reason,
        "metadata": {"max_turns_summary": True},
    })


def _is_cancelled(request: AgentRunRequest) -> bool:
    return bool(request.control and request.control.cancelled)


def _has_work_trace_events(events: list[AgentEvent]) -> bool:
    return any(event.type in {"work_trace_delta", "work_trace_item"} for event in events)


def _record_cancelled_stream_work_events(events: list[AgentEvent], streamed_events: list[AgentEvent]) -> None:
    seen = {
        (
            event.type,
            str((event.data if isinstance(event.data, dict) else {}).get("trace_type") or ""),
            str((event.data if isinstance(event.data, dict) else {}).get("text") or event.message or ""),
        )
        for event in events
        if event.type in {"work_trace_delta", "work_trace_item"}
    }
    for event in streamed_events:
        data = event.data if isinstance(event.data, dict) else {}
        key = (
            event.type,
            str(data.get("trace_type") or ""),
            str(data.get("text") or event.message or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        events.append(event)


def _cancelled_result(
    request: AgentRunRequest,
    *,
    messages: list[dict[str, Any]],
    events: list[AgentEvent],
    event_sink: AgentEventSink | None,
    turns: int,
    final_response: str | None,
    usage: TokenUsage | None = None,
) -> AgentRunResult:
    reason = request.control.reason if request.control else "cancelled"
    _record_event(
        events,
        AgentEvent("cancelled", "Agent run cancelled.", {"reason": reason}),
        event_sink,
    )
    return AgentRunResult(
        completed=False,
        final_response=final_response,
        messages=copy.deepcopy(messages),
        events=events,
        turns=turns,
        usage=usage,
        error="cancelled",
        cancelled=True,
    )


def _tool_guardrail_halted_result(
    *,
    messages: list[dict[str, Any]],
    events: list[AgentEvent],
    turns: int,
    final_response: str | None,
    decision: ToolGuardrailDecision,
    usage: TokenUsage | None = None,
) -> AgentRunResult:
    return AgentRunResult(
        completed=False,
        final_response=final_response,
        messages=copy.deepcopy(messages),
        events=events,
        turns=turns,
        usage=usage,
        error=decision.code or "tool_guardrail_halt",
    )


def _record_event(
    events: list[AgentEvent],
    event: AgentEvent,
    event_sink: AgentEventSink | None,
) -> None:
    events.append(event)
    if event_sink is None:
        return
    try:
        event_sink(event)
    except Exception:
        logger.debug("Agent event sink failed for %s", event.type, exc_info=True)


def _assistant_message_from_response(response: ModelResponse) -> dict[str, Any] | None:
    provider_data = dict(response.provider_data or {})
    if (
        not response.content
        and not response.tool_calls
        and not response.artifacts
        and not _has_replay_metadata(provider_data)
        and response.finish_reason != "incomplete"
    ):
        return None

    message: dict[str, Any] = {
        "role": "assistant",
        "content": response.content or "",
        "finish_reason": response.finish_reason,
    }
    codex_reasoning_items = provider_data.get("codex_reasoning_items")
    if isinstance(codex_reasoning_items, list) and codex_reasoning_items:
        message["codex_reasoning_items"] = codex_reasoning_items
    codex_message_items = provider_data.get("codex_message_items")
    if isinstance(codex_message_items, list) and codex_message_items:
        message["codex_message_items"] = codex_message_items
    reasoning_content = provider_data.get("reasoning_content")
    if isinstance(reasoning_content, str) and reasoning_content:
        message["reasoning_content"] = reasoning_content
    safe_provider_data = {
        key: value
        for key, value in provider_data.items()
        if key not in {"codex_reasoning_items", "codex_message_items", "reasoning_content"} and value not in (None, False, "", [])
    }
    if safe_provider_data:
        message["provider_data"] = safe_provider_data
    if response.tool_calls:
        message["tool_calls"] = [_tool_call_message(tool_call) for tool_call in response.tool_calls]
    if response.artifacts:
        message["artifacts"] = response.artifacts
    return message


def _tool_call_message(tool_call: ToolCall) -> dict[str, Any]:
    provider_data = dict(tool_call.provider_data or {})
    call_id = tool_call.call_id or tool_call.id
    message = {
        "id": call_id,
        "call_id": call_id,
        "type": "function",
        "function": {
            "name": tool_call.name,
            "arguments": tool_call.arguments,
        },
    }
    response_item_id = provider_data.get("response_item_id")
    if response_item_id:
        message["response_item_id"] = response_item_id
    thought_signature = provider_data.get("thought_signature")
    if isinstance(thought_signature, str) and thought_signature:
        message["thoughtSignature"] = thought_signature
    return message


def _has_replay_metadata(provider_data: dict[str, Any]) -> bool:
    if isinstance(provider_data.get("reasoning_content"), str) and provider_data.get("reasoning_content"):
        return True
    return any(
        isinstance(provider_data.get(key), list) and bool(provider_data.get(key))
        for key in ("codex_reasoning_items", "codex_message_items", "work_trace_items")
    )


def _tool_message_from_result(tool_call: ToolCall, tool_result: ToolResult) -> dict[str, Any]:
    return {
        "role": "tool",
        "name": tool_result.name or tool_call.name,
        "tool_call_id": tool_result.call_id or tool_call.call_id or tool_call.id,
        "content": tool_result.content,
    }


def _execute_tool(tool_executor: ToolExecutor, tool_call: ToolCall) -> ToolResult:
    try:
        raw_result = tool_executor.execute(tool_call)
    except Exception as error:
        return ToolResult(
            call_id=tool_call.call_id or tool_call.id,
            name=tool_call.name,
            content=f"Error: {error}",
            is_error=True,
        )
    return _normalize_tool_result(tool_call, raw_result)


def _append_executor_events(events: list[AgentEvent], tool_executor: ToolExecutor) -> None:
    drain = getattr(tool_executor, "drain_events", None)
    if not callable(drain):
        return
    try:
        drained = drain()
    except Exception:
        logger.debug("Tool executor event drain failed.", exc_info=True)
        return
    for event in drained:
        if isinstance(event, AgentEvent):
            events.append(event)


def _enforce_turn_tool_budget(tool_executor: ToolExecutor, tool_messages: list[dict[str, Any]]) -> None:
    enforce = getattr(tool_executor, "enforce_turn_budget", None)
    if not callable(enforce):
        return
    try:
        enforce(tool_messages)
    except Exception:
        logger.debug("Tool turn budget enforcement failed.", exc_info=True)


def _normalize_tool_result(tool_call: ToolCall, raw_result: ToolResult | str | dict[str, Any]) -> ToolResult:
    if isinstance(raw_result, ToolResult):
        if raw_result.call_id and raw_result.name:
            return raw_result
        return ToolResult(
            call_id=raw_result.call_id or tool_call.call_id or tool_call.id,
            name=raw_result.name or tool_call.name,
            content=raw_result.content,
            is_error=raw_result.is_error,
        )
    if isinstance(raw_result, dict):
        return ToolResult(
            call_id=str(raw_result.get("call_id") or tool_call.call_id or tool_call.id or ""),
            name=str(raw_result.get("name") or tool_call.name),
            content=str(raw_result.get("content") or raw_result.get("output") or ""),
            is_error=bool(raw_result.get("is_error", False)),
        )
    return ToolResult(
        call_id=tool_call.call_id or tool_call.id,
        name=tool_call.name,
        content=str(raw_result),
    )


def _model_response_event(response: ModelResponse, turn: int) -> AgentEvent:
    usage = response.usage
    provider_data = response.provider_data if isinstance(response.provider_data, dict) else {}
    web_search_call_count = _count_provider_items(provider_data.get("web_search_calls"))
    web_search_source_count = _count_provider_items(provider_data.get("web_search_sources"))
    data: dict[str, Any] = {
        "turn": turn,
        "finish_reason": response.finish_reason,
        "has_content": bool(response.content),
        "tool_call_count": len(response.tool_calls),
        "artifact_count": len(response.artifacts),
    }
    if web_search_call_count:
        data["web_search_call_count"] = web_search_call_count
    if web_search_source_count:
        data["web_search_source_count"] = web_search_source_count
    if usage is not None:
        data.update({
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        })
    message = "Model provider returned a response."
    if web_search_call_count:
        source_text = (
            f" and {web_search_source_count} source{'s' if web_search_source_count != 1 else ''}"
            if web_search_source_count
            else ""
        )
        message = (
            "Model provider returned a response with "
            f"{web_search_call_count} web search call{'s' if web_search_call_count != 1 else ''}"
            f"{source_text}."
        )
    return AgentEvent(
        "model_response",
        message,
        data,
    )


def _work_trace_events_from_response(response: ModelResponse, turn: int) -> list[AgentEvent]:
    provider_data = response.provider_data if isinstance(response.provider_data, dict) else {}
    raw_items = provider_data.get("work_trace_items")
    if not isinstance(raw_items, list):
        return []
    events: list[AgentEvent] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        trace_type = str(item.get("type") or "summary").strip() or "summary"
        key = (trace_type, text)
        if key in seen:
            continue
        seen.add(key)
        events.append(AgentEvent(
            "work_trace_item",
            text,
            {
                "turn": turn,
                "text": text,
                "trace_type": trace_type,
                "source": item.get("source") or "provider",
            },
        ))
    return events


def _reasoning_trace_events_from_response(response: ModelResponse, turn: int) -> list[AgentEvent]:
    provider_data = response.provider_data if isinstance(response.provider_data, dict) else {}
    text = str(provider_data.get("reasoning_content") or "").strip()
    if not text:
        return []
    return [AgentEvent(
        "work_trace_item",
        text,
        {
            "turn": turn,
            "text": text,
            "trace_type": "reasoning",
            "source": provider_data.get("provider") or "provider",
        },
    )]


def _with_ephemeral_messages(messages: list[dict[str, Any]], request_options: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(request_options, dict):
        return messages
    raw_messages = request_options.get("_paper_notes_ephemeral_messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return messages
    ephemeral: list[dict[str, Any]] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = item.get("content")
        if role not in {"system", "developer"} or not str(content or "").strip():
            continue
        ephemeral.append(copy.deepcopy(item))
    return [*ephemeral, *messages] if ephemeral else messages


def _count_provider_items(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _model_message_sanitized_event(result: MessageSanitizationResult) -> AgentEvent:
    return AgentEvent(
        "model_message_sanitized",
        "Repaired model-visible message history before provider call.",
        result.stats.to_event_data(),
    )


def _tool_call_recovery_event(
    result: ToolCallRecoveryResult,
    *,
    retry: int | None = None,
    max_retries: int | None = None,
) -> AgentEvent:
    data = result.stats.to_event_data()
    if retry is not None:
        data["retry"] = retry
    if max_retries is not None:
        data["max_retries"] = max_retries
    return AgentEvent(
        "tool_call_recovery",
        "Repaired or rejected model-emitted tool calls before execution.",
        data,
    )


def _accumulate_usage(total: TokenUsage, usage: TokenUsage | None) -> None:
    if usage is None:
        return
    total.input_tokens += usage.input_tokens
    total.output_tokens += usage.output_tokens
    total.total_tokens += usage.total_tokens or usage.input_tokens + usage.output_tokens


def _usage_or_none(usage: TokenUsage) -> TokenUsage | None:
    if not usage.input_tokens and not usage.output_tokens and not usage.total_tokens:
        return None
    return TokenUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def _tool_call_data(
    tool_call: ToolCall,
    *,
    read_only: bool | None = None,
    tool_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = {
        "id": tool_call.call_id or tool_call.id,
        "name": tool_call.name,
        "arguments": tool_call.arguments,
    }
    if read_only is not None:
        data["read_only"] = read_only
    if tool_metadata:
        data.update({
            "mutating": bool(tool_metadata.get("mutating")),
            "risk": tool_metadata.get("risk") or "",
            "write_mode": tool_metadata.get("write_mode") or "",
        })
    return data


def _tool_result_data(tool_result: ToolResult) -> dict[str, Any]:
    data = {
        "call_id": tool_result.call_id,
        "name": tool_result.name,
        "is_error": tool_result.is_error,
    }
    payload = _json_object_payload(tool_result.content)
    if payload:
        for key in (
            "success",
            "changed",
            "error",
            "code",
            "note_id",
            "message",
            "summary",
            "heading",
            "position",
            "path",
        ):
            if key in payload:
                data[key] = _safe_event_value(payload.get(key))
    if tool_result.metadata:
        data.update(tool_result.metadata)
    return data


def _artifacts_from_tool_result(tool_result: ToolResult) -> list[dict[str, Any]]:
    payload = _json_object_payload(tool_result.content)
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, list):
        return []
    return [dict(artifact) for artifact in artifacts if isinstance(artifact, dict)]


def _extend_artifacts(target: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> None:
    if not artifacts:
        return
    seen = {str(item.get("id") or "") for item in target if isinstance(item, dict)}
    for artifact in artifacts:
        artifact_id = str(artifact.get("id") or "")
        if artifact_id and artifact_id in seen:
            continue
        target.append(artifact)
        if artifact_id:
            seen.add(artifact_id)


def _json_object_payload(content: str) -> dict[str, Any]:
    if not isinstance(content, str) or not content.strip():
        return {}
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_event_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:2_000]
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        return value[:20]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in list(value.items())[:20]:
            if isinstance(item, str):
                safe[str(key)] = item[:500]
            elif isinstance(item, int | float | bool) or item is None:
                safe[str(key)] = item
        return safe
    return str(value)[:500]


def _tool_guardrail_event(decision: ToolGuardrailDecision, event_type: str) -> AgentEvent:
    return AgentEvent(event_type, decision.message, decision.to_metadata())


def _tool_arguments_for_guardrail(tool_call: ToolCall) -> dict[str, Any]:
    raw_arguments = tool_call.arguments or ""
    if not raw_arguments.strip():
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {"__raw_arguments": raw_arguments}
    return parsed if isinstance(parsed, dict) else {"__raw_arguments": raw_arguments}


def _tool_is_read_only(tool_executor: ToolExecutor | None, tool_name: str) -> bool:
    checker = getattr(tool_executor, "is_read_only", None)
    if not callable(checker):
        return False
    try:
        return bool(checker(tool_name))
    except Exception:
        logger.debug("Tool read-only check failed for %s", tool_name, exc_info=True)
        return False


def _tool_metadata(tool_executor: ToolExecutor | None, tool_name: str) -> dict[str, Any]:
    metadata = getattr(tool_executor, "tool_metadata", None)
    if not callable(metadata):
        return {}
    try:
        value = metadata(tool_name)
    except Exception:
        logger.debug("Tool metadata lookup failed for %s", tool_name, exc_info=True)
        return {}
    return value if isinstance(value, dict) else {}


def _should_warn_for_mutating_tool(tool_metadata: dict[str, Any]) -> bool:
    return bool(tool_metadata.get("mutating")) and str(tool_metadata.get("write_mode") or "") == "warn"


def _all_tool_calls_housekeeping(tool_calls: list[ToolCall]) -> bool:
    housekeeping_tools = {"persistent_memory", "todo"}
    return bool(tool_calls) and all(tool_call.name in housekeeping_tools for tool_call in tool_calls)


def _should_recover_empty_after_tools(response: ModelResponse, messages: list[dict[str, Any]]) -> bool:
    if response.finish_reason == "incomplete" or response.tool_calls:
        return False
    if response.artifacts:
        return False
    if response.content and response.content.strip():
        return False
    return any(message.get("role") == "tool" for message in messages[-6:])


def _append_empty_tool_recovery_nudge(messages: list[dict[str, Any]], response: ModelResponse) -> None:
    if (
        messages
        and messages[-1].get("role") == "assistant"
        and not messages[-1].get("tool_calls")
        and not str(messages[-1].get("content") or "").strip()
    ):
        messages[-1]["content"] = "(empty)"
        messages[-1]["_empty_recovery_synthetic"] = True
    else:
        messages.append({
            "role": "assistant",
            "content": "(empty)",
            "finish_reason": response.finish_reason,
            "_empty_recovery_synthetic": True,
        })
    messages.append({
        "role": "user",
        "content": (
            "You just executed tool calls but returned an empty response. "
            "Please process the tool results above and continue with the task."
        ),
        "_empty_recovery_synthetic": True,
    })
