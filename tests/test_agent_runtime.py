from __future__ import annotations

import json

from agent_runtime import AgentRunControl, AgentRunRequest, AgentRunner, ToolResult
from tool_safety import ToolGuardrailConfig
from model_providers.types import ModelRequest, ModelResponse, ModelStreamEvent, TokenUsage, ToolCall


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)


class FakeToolExecutor:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(call_id=tool_call.call_id, name=tool_call.name, content='{"answer": "found"}')


class FixedToolExecutor:
    def __init__(self, result: ToolResult, *, read_only: bool = False) -> None:
        self.result = result
        self.read_only = read_only
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            call_id=tool_call.call_id or tool_call.id,
            name=tool_call.name,
            content=self.result.content,
            is_error=self.result.is_error,
        )

    def is_read_only(self, tool_name: str) -> bool:
        return self.read_only


def test_agent_run_request_defaults_to_hermes_iteration_budget():
    assert AgentRunRequest(model="test-model").max_turns == 90


def test_runner_returns_text_response():
    provider = FakeProvider([ModelResponse(content="Hello from the agent.")])
    runner = AgentRunner(provider)

    result = runner.run(AgentRunRequest(model="test-model", messages=[{"role": "user", "content": "Hi"}]))

    assert result.completed is True
    assert result.final_response == "Hello from the agent."
    assert provider.requests[0].model == "test-model"
    assert result.messages[-1]["role"] == "assistant"


def test_runner_emits_events_to_sink():
    provider = FakeProvider([ModelResponse(content="Hello from the agent.")])
    events = []
    runner = AgentRunner(provider, event_sink=events.append)

    result = runner.run(AgentRunRequest(model="test-model", messages=[]))

    assert result.completed is True
    assert [event.type for event in events] == ["model_request", "model_response", "completed"]
    assert events == result.events


def test_runner_streams_model_delta_events_to_sink():
    class StreamingProvider(FakeProvider):
        def stream_generate(self, request: ModelRequest, event_sink=None) -> ModelResponse:
            self.requests.append(request)
            if event_sink is not None:
                event_sink(ModelStreamEvent(type="text_delta", delta="Hel", text="Hel"))
                event_sink(ModelStreamEvent(type="text_delta", delta="lo", text="Hello"))
            return self.responses.pop(0)

    provider = StreamingProvider([ModelResponse(content="Hello")])
    events = []
    runner = AgentRunner(provider, event_sink=events.append)

    result = runner.run(AgentRunRequest(model="test-model", messages=[]))

    assert result.completed is True
    assert result.final_response == "Hello"
    assert [event.data["delta"] for event in events if event.type == "model_delta"] == ["Hel", "lo"]
    assert "model_delta" not in [event.type for event in result.events]


def test_runner_streams_work_trace_events_to_sink_and_records_final_items():
    class StreamingProvider(FakeProvider):
        def stream_generate(self, request: ModelRequest, event_sink=None) -> ModelResponse:
            self.requests.append(request)
            if event_sink is not None:
                event_sink(ModelStreamEvent(type="reasoning_summary_delta", delta="Checking", text="Checking"))
                event_sink(ModelStreamEvent(type="reasoning_summary_done", text="Checking note metadata."))
            return self.responses.pop(0)

    provider = StreamingProvider([ModelResponse(
        content="Done",
        provider_data={"work_trace_items": [{"type": "summary", "text": "Checked note metadata.", "source": "provider"}]},
    )])
    events = []
    runner = AgentRunner(provider, event_sink=events.append)

    result = runner.run(AgentRunRequest(model="test-model", messages=[]))

    assert [event.type for event in events if event.type.startswith("work_trace")] == [
        "work_trace_delta",
        "work_trace_item",
        "work_trace_item",
    ]
    assert [event.message for event in result.events if event.type == "work_trace_item"] == ["Checked note metadata."]


def test_runner_aggregates_usage_from_model_responses():
    provider = FakeProvider([
        ModelResponse(
            content="Hello from the agent.",
            usage=TokenUsage(input_tokens=10, output_tokens=3, total_tokens=13),
        )
    ])
    runner = AgentRunner(provider)

    result = runner.run(AgentRunRequest(model="test-model", messages=[]))

    assert result.usage is not None
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 3
    assert result.usage.total_tokens == 13
    assert result.events[1].data["input_tokens"] == 10


def test_runner_model_response_event_reports_provider_native_web_search():
    provider = FakeProvider([
        ModelResponse(
            content="Found current sources.",
            provider_data={
                "web_search_calls": [
                    {"id": "ws_1", "status": "completed", "action": {"query": "paper notes"}},
                    {"id": "ws_2", "status": "completed", "queries": ["native web search"]},
                ],
                "web_search_sources": [
                    {"url": "https://example.test/one"},
                    {"url": "https://example.test/two"},
                ],
            },
        )
    ])
    runner = AgentRunner(provider)

    result = runner.run(AgentRunRequest(model="test-model", messages=[]))

    response_event = result.events[1]
    assert response_event.type == "model_response"
    assert response_event.data["tool_call_count"] == 0
    assert response_event.data["web_search_call_count"] == 2
    assert response_event.data["web_search_source_count"] == 2
    assert response_event.data["web_search_queries"] == ["paper notes", "native web search"]
    assert response_event.message == "Model provider returned a response with 2 web search calls and 2 sources."


def test_runner_cancels_before_provider_call():
    control = AgentRunControl()
    control.cancel("stop")
    provider = FakeProvider([ModelResponse(content="Should not run.")])
    runner = AgentRunner(provider)

    result = runner.run(AgentRunRequest(model="test-model", messages=[], control=control))

    assert result.completed is False
    assert result.cancelled is True
    assert result.error == "cancelled"
    assert provider.requests == []
    assert result.events[-1].type == "cancelled"


def test_runner_cancels_after_provider_without_appending_response():
    control = AgentRunControl()

    class CancellingProvider(FakeProvider):
        def generate(self, request: ModelRequest) -> ModelResponse:
            response = super().generate(request)
            control.cancel("stop")
            return response

    provider = CancellingProvider([ModelResponse(content="Should not persist.")])
    runner = AgentRunner(provider)

    result = runner.run(AgentRunRequest(
        model="test-model",
        messages=[{"role": "user", "content": "Hi"}],
        control=control,
    ))

    assert result.cancelled is True
    assert result.final_response is None
    assert result.messages == [{"role": "user", "content": "Hi"}]


def test_runner_cancellation_keeps_streamed_work_trace():
    control = AgentRunControl()
    events = []

    class CancellingStreamingProvider(FakeProvider):
        def stream_generate(self, request: ModelRequest, event_sink=None) -> ModelResponse:
            self.requests.append(request)
            if event_sink is not None:
                event_sink(ModelStreamEvent(
                    type="reasoning_summary_done",
                    text="Checked page context.",
                ))
            control.cancel("stop")
            return ModelResponse(content="Should not persist.")

    provider = CancellingStreamingProvider([])
    runner = AgentRunner(provider, event_sink=events.append)

    result = runner.run(AgentRunRequest(
        model="test-model",
        messages=[{"role": "user", "content": "Hi"}],
        control=control,
        stream_events_enabled=True,
    ))

    assert result.cancelled is True
    assert result.final_response is None
    assert result.messages[-1]["role"] == "assistant"
    assert result.messages[-1]["content"] == ""
    assert [event.message for event in result.events if event.type == "work_trace_item"] == ["Checked page context."]


def test_runner_cancels_before_tool_execution():
    control = AgentRunControl()
    tool_call = ToolCall(id="call_1", name="search_notes", arguments="{}")
    provider = FakeProvider([ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls")])
    executor = FakeToolExecutor()

    def cancel_on_tool_call(event):
        if event.type == "tool_call":
            control.cancel("stop")

    runner = AgentRunner(provider, tool_executor=executor, event_sink=cancel_on_tool_call)

    result = runner.run(AgentRunRequest(
        model="test-model",
        messages=[{"role": "user", "content": "Search"}],
        control=control,
    ))

    assert result.cancelled is True
    assert executor.calls == []
    assert result.messages == [{"role": "user", "content": "Search"}]


def test_runner_executes_tool_call_then_continues():
    tool_call = ToolCall(id="call_1", name="search_notes", arguments='{"query": "attention"}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content="I found one relevant note.", finish_reason="stop"),
    ])
    executor = FakeToolExecutor()
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(model="test-model", messages=[{"role": "user", "content": "Search"}]))

    assert result.completed is True
    assert result.final_response == "I found one relevant note."
    assert len(provider.requests) == 2
    assert executor.calls == [tool_call]
    assert provider.requests[1].messages[-1]["role"] == "tool"
    assert provider.requests[1].messages[-1]["tool_call_id"] == "call_1"


def test_runner_continues_incomplete_model_response_and_persists_replay_metadata():
    provider = FakeProvider([
        ModelResponse(
            content=None,
            finish_reason="incomplete",
            provider_data={
                "response_id": "resp_1",
                "status": "incomplete",
                "codex_reasoning_items": [{
                    "type": "reasoning",
                    "encrypted_content": "opaque",
                    "summary": [],
                }],
                "codex_message_items": [{
                    "type": "message",
                    "role": "assistant",
                    "status": "incomplete",
                    "content": [{"type": "output_text", "text": ""}],
                }],
            },
        ),
        ModelResponse(content="Finished.", finish_reason="stop"),
    ])
    runner = AgentRunner(provider)

    result = runner.run(AgentRunRequest(model="test-model", messages=[{"role": "user", "content": "Hi"}]))

    assert result.completed is True
    assert result.final_response == "Finished."
    assert len(provider.requests) == 2
    assert result.messages[1]["finish_reason"] == "incomplete"
    assert result.messages[1]["codex_reasoning_items"][0]["encrypted_content"] == "opaque"
    assert provider.requests[1].messages[-1]["codex_reasoning_items"][0]["encrypted_content"] == "opaque"
    assert "model_continuation" in [event.type for event in result.events]


def test_runner_exhausts_repeated_incomplete_model_responses():
    provider = FakeProvider([
        ModelResponse(content=None, finish_reason="incomplete"),
        ModelResponse(content=None, finish_reason="incomplete"),
    ])
    runner = AgentRunner(provider)

    result = runner.run(AgentRunRequest(
        model="test-model",
        messages=[{"role": "user", "content": "Hi"}],
        max_turns=3,
        max_continuation_turns=1,
    ))

    assert result.completed is False
    assert result.error == "model_incomplete_continuation_exhausted"
    assert len(provider.requests) == 2
    assert result.events[-1].type == "model_continuation_exhausted"


def test_runner_sanitizes_invalid_roles_and_orphan_tool_results_before_model_call():
    provider = FakeProvider([ModelResponse(content="Cleaned.")])
    runner = AgentRunner(provider)

    result = runner.run(AgentRunRequest(
        model="test-model",
        messages=[
            {"role": "user", "content": "Hi"},
            {"role": "debug", "content": "not for model"},
            {"role": "tool", "tool_call_id": "orphan", "content": "stale result"},
        ],
    ))

    assert result.completed is True
    assert provider.requests[0].messages == [{"role": "user", "content": "Hi"}]
    sanitize_event = [event for event in result.events if event.type == "model_message_sanitized"][0]
    assert sanitize_event.data["removed_invalid_roles"] == 1
    assert sanitize_event.data["removed_orphaned_tool_results"] == 1
    assert sanitize_event.data["orphaned_tool_call_ids"] == ["orphan"]


def test_runner_inserts_synthetic_result_for_missing_tool_call_before_model_call():
    provider = FakeProvider([ModelResponse(content="Recovered.")])
    runner = AgentRunner(provider)

    result = runner.run(AgentRunRequest(
        model="test-model",
        messages=[{
            "role": "assistant",
            "content": "",
            "codex_reasoning_items": [{
                "type": "reasoning",
                "encrypted_content": "opaque",
                "summary": [],
            }],
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }],
        }],
    ))

    assert result.completed is True
    request_messages = provider.requests[0].messages
    assert request_messages[0]["codex_reasoning_items"][0]["encrypted_content"] == "opaque"
    assert request_messages[1]["role"] == "tool"
    assert request_messages[1]["name"] == "lookup"
    assert request_messages[1]["tool_call_id"] == "call_1"
    payload = json.loads(request_messages[1]["content"])
    assert payload["success"] is False
    assert payload["code"] == "missing_tool_result_synthetic"
    sanitize_event = [event for event in result.events if event.type == "model_message_sanitized"][0]
    assert sanitize_event.data["inserted_missing_tool_results"] == 1
    assert sanitize_event.data["missing_tool_call_ids"] == ["call_1"]


def test_runner_returns_pending_tool_calls_without_executor():
    tool_call = ToolCall(id="call_1", name="search_notes", arguments="{}")
    provider = FakeProvider([ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls")])
    runner = AgentRunner(provider)

    result = runner.run(AgentRunRequest(model="test-model", messages=[{"role": "user", "content": "Search"}]))

    assert result.completed is False
    assert result.error == "tool_executor_missing"
    assert result.pending_tool_calls == [tool_call]
    assert result.events[-1].type == "tool_calls_pending"


def test_runner_tool_error_events_include_structured_error_details():
    tool_call = ToolCall(id="call_1", name="lookup", arguments='{"query": "missing"}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content="Recovered.", finish_reason="stop"),
    ])
    executor = FixedToolExecutor(ToolResult(
        call_id="call_1",
        name="lookup",
        content='{"success": false, "error": "Could not find target text.", "code": "target_not_found"}',
        is_error=True,
    ))
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=3))
    tool_error = [event for event in result.events if event.type == "tool_error"][0]

    assert result.completed is True
    assert tool_error.data["error"] == "Could not find target text."
    assert tool_error.data["code"] == "target_not_found"


def test_runner_retries_invalid_json_tool_arguments_before_executing():
    bad_call = ToolCall(id="call_bad", name="lookup", arguments='{"query": unquoted}')
    good_call = ToolCall(id="call_good", name="lookup", arguments='{"query": "fixed"}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[bad_call], finish_reason="tool_calls"),
        ModelResponse(content=None, tool_calls=[good_call], finish_reason="tool_calls"),
        ModelResponse(content="Recovered.", finish_reason="stop"),
    ])
    executor = FakeToolExecutor()
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(
        model="test-model",
        messages=[{"role": "user", "content": "Search"}],
        max_turns=4,
    ))

    assert result.completed is True
    assert result.final_response == "Recovered."
    assert executor.calls == [good_call]
    assert provider.requests[1].messages == [{"role": "user", "content": "Search"}]
    recovery_event = [event for event in result.events if event.type == "tool_call_recovery"][0]
    assert recovery_event.data["retry"] == 1
    assert recovery_event.data["invalid_arguments"][0]["name"] == "lookup"


def test_runner_injects_tool_errors_after_repeated_invalid_json_arguments():
    bad_call = ToolCall(id="call_bad", name="lookup", arguments='{"query": unquoted}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[bad_call], finish_reason="tool_calls"),
        ModelResponse(content=None, tool_calls=[bad_call], finish_reason="tool_calls"),
        ModelResponse(content=None, tool_calls=[bad_call], finish_reason="tool_calls"),
        ModelResponse(content="I fixed the call format.", finish_reason="stop"),
    ])
    executor = FakeToolExecutor()
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=5))

    assert result.completed is True
    assert executor.calls == []
    assert len(provider.requests) == 4
    request_messages = provider.requests[3].messages
    assert request_messages[-2]["role"] == "assistant"
    assert request_messages[-1]["role"] == "tool"
    assert request_messages[-1]["tool_call_id"] == "call_bad"
    payload = json.loads(request_messages[-1]["content"])
    assert payload["success"] is False
    assert payload["code"] == "invalid_tool_arguments_json"
    assert "tool_call_recovery_injected" in [event.type for event in result.events]


def test_runner_stops_on_truncated_tool_arguments():
    bad_call = ToolCall(id="call_bad", name="lookup", arguments='{"query": "unfinished"')
    provider = FakeProvider([ModelResponse(content=None, tool_calls=[bad_call], finish_reason="tool_calls")])
    executor = FakeToolExecutor()
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=3))

    assert result.completed is False
    assert result.error == "tool_arguments_truncated"
    assert executor.calls == []
    recovery_event = [event for event in result.events if event.type == "tool_call_recovery"][0]
    assert recovery_event.data["invalid_arguments"][0]["truncated"] is True


def test_runner_deduplicates_identical_tool_calls_before_execution():
    first = ToolCall(id="call_1", name="lookup", arguments='{"query": "same"}')
    duplicate = ToolCall(id="call_2", name="lookup", arguments='{"query": "same"}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[first, duplicate], finish_reason="tool_calls"),
        ModelResponse(content="Used one result.", finish_reason="stop"),
    ])
    executor = FakeToolExecutor()
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=3))

    assert result.completed is True
    assert executor.calls == [first]
    assert len(result.messages[0]["tool_calls"]) == 1
    recovery_event = [event for event in result.events if event.type == "tool_call_recovery"][0]
    assert recovery_event.data["deduplicated_call_ids"] == ["call_2"]


def test_runner_nudges_model_after_empty_response_following_tool_results():
    tool_call = ToolCall(id="call_1", name="lookup", arguments='{"query": "same"}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content="", finish_reason="stop"),
        ModelResponse(content="Using the tool result.", finish_reason="stop"),
    ])
    executor = FakeToolExecutor()
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=4))

    assert result.completed is True
    assert result.final_response == "Using the tool result."
    assert provider.requests[2].messages[-1]["role"] == "user"
    assert provider.requests[2].messages[-1]["_empty_recovery_synthetic"] is True
    assert "tool results above" in provider.requests[2].messages[-1]["content"]
    assert "model_empty_after_tool_nudge" in [event.type for event in result.events]


def test_runner_uses_prior_content_when_housekeeping_tool_followup_is_empty():
    tool_call = ToolCall(id="call_1", name="persistent_memory", arguments='{"action": "read", "target": "project"}')
    provider = FakeProvider([
        ModelResponse(content="I will remember that.", tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content="", finish_reason="stop"),
    ])
    executor = FakeToolExecutor()
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=3))

    assert result.completed is True
    assert result.final_response == "I will remember that."
    event_types = [event.type for event in result.events]
    assert "model_empty_after_tool_fallback" in event_types
    assert "model_empty_after_tool_nudge" not in event_types


def test_runner_stops_at_max_turns():
    tool_call = ToolCall(id="call_1", name="search_notes", arguments="{}")
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content="Stopped after the tool budget.", finish_reason="stop"),
    ])
    runner = AgentRunner(provider, tool_executor=FakeToolExecutor())

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=1))

    assert result.completed is False
    assert result.error == "max_turns_exceeded"
    assert result.turns == 1
    assert result.final_response == "Stopped after the tool budget."
    assert provider.requests[1].tools == []
    assert "maximum tool-calling iterations" in provider.requests[1].messages[-1]["content"]
    assert result.messages[-1]["content"] == "Stopped after the tool budget."
    assert not any("_max_turns_summary_request" in message for message in result.messages)
    assert "halted" in [event.type for event in result.events]
    assert "max_turns_summary_request" in [event.type for event in result.events]


def test_runner_injects_iteration_budget_warnings_without_persisting_them():
    responses = [
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id=f"call_{index}", name="lookup", arguments='{"query": "same"}')],
            finish_reason="tool_calls",
        )
        for index in range(20)
    ]
    responses.append(ModelResponse(content="Budget summary.", finish_reason="stop"))
    provider = FakeProvider(responses)
    runner = AgentRunner(provider, tool_executor=FakeToolExecutor())

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=20))

    warning_events = [event for event in result.events if event.type == "iteration_budget_warning"]
    assert [event.data["level"] for event in warning_events] == ["notice", "urgent", "final"]
    notice_payload = json.loads(provider.requests[14].messages[-1]["content"])
    urgent_payload = json.loads(provider.requests[17].messages[-1]["content"])
    final_payload = json.loads(provider.requests[18].messages[-1]["content"])
    assert notice_payload["_budget_warning"]["level"] == "notice"
    assert urgent_payload["_budget_warning"]["level"] == "urgent"
    assert final_payload["_budget_warning"]["level"] == "final"
    assert provider.requests[-1].tools == []
    assert not any("_budget_warning" in str(message.get("content", "")) for message in result.messages)


def test_runner_uses_fallback_when_max_turn_summary_fails():
    tool_call = ToolCall(id="call_1", name="search_notes", arguments="{}")

    class FailingSummaryProvider(FakeProvider):
        def generate(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            if len(self.requests) == 1:
                return ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls")
            raise RuntimeError("summary failed")

    provider = FailingSummaryProvider([])
    runner = AgentRunner(provider, tool_executor=FakeToolExecutor())

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=1))

    assert result.completed is False
    assert result.error == "max_turns_exceeded"
    assert result.final_response
    assert "maximum tool-calling iterations" in result.final_response
    assert result.messages[-1]["metadata"]["max_turns_summary"] is True
    assert provider.requests[1].tools == []
    assert "max_turns_summary_failed" in [event.type for event in result.events]


def test_runner_warns_on_repeated_exact_tool_failure():
    tool_call = ToolCall(id="call_1", name="lookup", arguments='{"query": "same"}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content="Changed strategy.", finish_reason="stop"),
    ])
    executor = FixedToolExecutor(ToolResult(content='{"error": "missing"}', is_error=True))
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=3))

    assert result.completed is True
    assert len(executor.calls) == 2
    assert "tool_warning" in [event.type for event in result.events]
    assert "Tool loop warning" in result.messages[-2]["content"]


def test_runner_blocks_repeated_exact_tool_failure_without_executing_again():
    tool_call = ToolCall(id="call_1", name="lookup", arguments='{"query": "same"}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content="I will answer without retrying.", finish_reason="stop"),
    ])
    executor = FixedToolExecutor(ToolResult(content='{"error": "missing"}', is_error=True))
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(
        model="test-model",
        messages=[],
        max_turns=3,
        tool_guardrails=ToolGuardrailConfig(exact_failure_block_after=1),
    ))

    assert result.completed is True
    assert len(executor.calls) == 1
    assert "tool_blocked" in [event.type for event in result.events]
    blocked = json.loads(result.messages[-2]["content"])
    assert blocked["guardrail"]["action"] == "block"
    assert blocked["guardrail"]["signature"]["tool_name"] == "lookup"


def test_runner_warns_when_read_only_tool_returns_same_result():
    tool_call = ToolCall(id="call_1", name="session_search", arguments='{"query": "same"}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content="Using the search result.", finish_reason="stop"),
    ])
    executor = FixedToolExecutor(ToolResult(content='{"matches": []}'), read_only=True)
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=3))

    assert result.completed is True
    assert len(executor.calls) == 2
    warning = [event for event in result.events if event.type == "tool_warning"][0]
    assert warning.data["code"] == "idempotent_no_progress_warning"


def test_runner_does_not_apply_no_progress_warning_to_mutating_tool():
    tool_call = ToolCall(id="call_1", name="persistent_memory", arguments='{"action": "add", "text": "same"}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        ModelResponse(content="Memory handled.", finish_reason="stop"),
    ])
    executor = FixedToolExecutor(ToolResult(content='{"success": true}'), read_only=False)
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(model="test-model", messages=[], max_turns=3))

    assert result.completed is True
    assert len(executor.calls) == 2
    assert "tool_warning" not in [event.type for event in result.events]


def test_runner_halts_on_repeated_same_tool_failures():
    first = ToolCall(id="call_1", name="lookup", arguments='{"query": "a"}')
    second = ToolCall(id="call_2", name="lookup", arguments='{"query": "b"}')
    provider = FakeProvider([
        ModelResponse(content=None, tool_calls=[first], finish_reason="tool_calls"),
        ModelResponse(content=None, tool_calls=[second], finish_reason="tool_calls"),
        ModelResponse(content="Should not be requested.", finish_reason="stop"),
    ])
    executor = FixedToolExecutor(ToolResult(content='{"error": "missing"}', is_error=True))
    runner = AgentRunner(provider, tool_executor=executor)

    result = runner.run(AgentRunRequest(
        model="test-model",
        messages=[],
        max_turns=4,
        tool_guardrails=ToolGuardrailConfig(
            exact_failure_block_after=10,
            same_tool_failure_halt_after=2,
        ),
    ))

    assert result.completed is False
    assert result.error == "same_tool_failure_halt"
    assert len(executor.calls) == 2
    assert len(provider.requests) == 2
    assert result.events[-1].type == "tool_halted"
