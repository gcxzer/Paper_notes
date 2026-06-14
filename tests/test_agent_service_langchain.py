from __future__ import annotations

import json
from dataclasses import dataclass

from langchain_core.language_models.fake_chat_models import FakeListChatModel, FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.tools import StructuredTool

from agent_runtime import ATTACHMENT_ONLY_MESSAGE, AgentService, AgentServiceRequest
from agent_runtime.service import _with_generated_artifacts_on_latest_assistant
from agent_runtime.streaming import events_from_langchain_chunk
from agent_sessions import AgentSessionStore
from app_config import AppConfig


def _config() -> AppConfig:
    return AppConfig(
        data={
            "models": {
                "default": "main",
                "main": {
                    "provider": "openai",
                    "name": "gpt-5.5",
                    "options": {},
                },
            },
        },
        path=None,
    )


def test_agent_service_creates_session_and_persists_transcript(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="Hello from LangChain.")])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    result = service.run(AgentServiceRequest(message="Hello", title="Paper chat", enable_tools=False))

    assert result.created_session is True
    assert result.response == "Hello from LangChain."
    assert result.session.metadata.title == "Paper chat"
    assert result.session.metadata.provider == "openai"
    assert result.session.metadata.model == "gpt-5.5"
    assert [message["role"] for message in result.messages] == ["user", "assistant"]
    assert [message["content"] for message in result.messages] == ["Hello", "Hello from LangChain."]
    assert store.require_session(result.session_id).messages == result.messages


def test_agent_service_streams_model_deltas_and_persists_transcript(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeListChatModel(responses=["Hello stream."])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    events = list(service.stream(AgentServiceRequest(message="Hello", title="Stream chat", enable_tools=False)))

    start_events = [event for event in events if event.event == "work_trace_item"]
    deltas = [event.data["delta"] for event in events if event.event == "model_delta"]
    final = next(event.data["result"] for event in events if event.event == "final")
    assert start_events[0].data["text"] == "Starting agent run."
    assert events.index(start_events[0]) < events.index(next(event for event in events if event.event == "final"))
    assert "".join(deltas) == "Hello stream."
    assert final.response == "Hello stream."
    assert final.run_trace["status"] == "completed"
    assert final.run_trace["events"][0]["message"] == "Starting agent run."
    assert final.messages[-1]["runTrace"]["durationMs"] >= 0
    assert [message["content"] for message in store.require_session(final.session_id).messages] == ["Hello", "Hello stream."]
    assert store.require_session(final.session_id).messages[-1]["runTrace"]["status"] == "completed"


def test_agent_service_preserves_existing_run_trace_on_next_stream(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeListChatModel(responses=["First stream.", "Second stream."])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    first_events = list(service.stream(AgentServiceRequest(
        message="First",
        title="Trace preservation",
        enable_tools=False,
        metadata={"requestId": "first-request"},
    )))
    first_final = next(event.data["result"] for event in first_events if event.event == "final")
    first_trace = store.require_session(first_final.session_id).messages[-1]["runTrace"]

    second_events = list(service.stream(AgentServiceRequest(
        message="Second",
        session_id=first_final.session_id,
        enable_tools=False,
        metadata={"requestId": "second-request"},
    )))
    second_final = next(event.data["result"] for event in second_events if event.event == "final")
    messages = store.require_session(second_final.session_id).messages

    assert messages[1]["content"] == "First stream."
    assert messages[1]["runTrace"] == first_trace
    assert messages[-1]["content"] == "Second stream."
    assert messages[-1]["runTrace"]["requestId"] == "second-request"


def test_agent_service_streams_codex_internal_work_trace(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[
        AIMessage(
            content="Created file.",
            response_metadata={
                "codex_work_trace": [{
                    "text": "Codex changed file: deepseek-v4-page1-translation.md",
                    "traceType": "tool",
                    "source": "codex",
                    "data": {"type": "fileChange"},
                }]
            },
        )
    ])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    events = list(service.stream(AgentServiceRequest(message="Write a markdown file.", enable_tools=False)))

    work_texts = [event.data["text"] for event in events if event.event == "work_trace_item"]
    final = next(event.data["result"] for event in events if event.event == "final")
    assert "Codex changed file: deepseek-v4-page1-translation.md" in work_texts
    assert any(
        event["message"] == "Codex changed file: deepseek-v4-page1-translation.md"
        for event in final.run_trace["events"]
    )


def test_agent_service_streams_codex_model_trace(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[
        AIMessage(
            content="Final answer.",
            response_metadata={
                "codex_model_trace": [{
                    "text": "Reading the visible page.",
                    "traceType": "summary",
                    "source": "codex",
                    "data": {"type": "reasoning"},
                }]
            },
        )
    ])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    events = list(service.stream(AgentServiceRequest(message="Explain.", enable_tools=False)))

    work_items = [event for event in events if event.event == "work_trace_item"]
    final = next(event.data["result"] for event in events if event.event == "final")
    assert any(item.data["traceType"] == "summary" and item.data["text"] == "Reading the visible page." for item in work_items)
    assert any(
        event["stage"] == "summary" and event["message"] == "Reading the visible page."
        for event in final.run_trace["events"]
    )


def test_agent_service_streams_provider_reasoning_as_single_work_trace(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[
        AIMessage(
            content="Final answer.",
            additional_kwargs={"reasoning_content": "Checked page context, then answered directly."},
            response_metadata={"model_provider": "deepseek"},
        )
    ])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    events = list(service.stream(AgentServiceRequest(message="Explain.", enable_tools=False)))

    reasoning_items = [
        event for event in events
        if event.event == "work_trace_item" and event.data.get("traceType") == "reasoning"
    ]
    final = next(event.data["result"] for event in events if event.event == "final")
    persisted = store.require_session(final.session_id).messages[-1]

    assert len(reasoning_items) == 1
    assert reasoning_items[0].data["text"] == "Checked page context, then answered directly."
    assert any(
        event["stage"] == "reasoning" and event["message"] == "Checked page context, then answered directly."
        for event in final.run_trace["events"]
    )
    assert "reasoning_content" not in persisted.get("metadata", {}).get("additional_kwargs", {})


def test_agent_service_hides_provider_reasoning_when_thinking_disabled(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[
        AIMessage(
            content="Final answer.",
            additional_kwargs={"reasoning_content": "Hidden provider reasoning."},
            response_metadata={"model_provider": "deepseek"},
        )
    ])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    events = list(service.stream(AgentServiceRequest(
        message="Explain.",
        provider="deepseek",
        model="deepseek-v4-flash",
        model_options={"thinking": {"type": "disabled"}},
        enable_tools=False,
    )))

    final = next(event.data["result"] for event in events if event.event == "final")
    assert all(
        event.data.get("text") != "Hidden provider reasoning."
        for event in events
        if event.event in {"work_trace_item", "work_trace_delta"}
    )
    assert all(
        event["message"] != "Hidden provider reasoning."
        for event in final.run_trace["events"]
    )


def test_agent_service_hides_provider_reasoning_when_gemini_minimal_thinking(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[
        AIMessage(
            content="Final answer.",
            additional_kwargs={"reasoning_content": "Gemini thought summary."},
            response_metadata={"model_provider": "gemini"},
        )
    ])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    events = list(service.stream(AgentServiceRequest(
        message="Explain.",
        provider="gemini",
        model="gemini-3-flash-preview",
        model_options={"thinking_level": "minimal", "include_thoughts": False},
        enable_tools=False,
    )))

    final = next(event.data["result"] for event in events if event.event == "final")
    assert all(
        event.data.get("text") != "Gemini thought summary."
        for event in events
        if event.event in {"work_trace_item", "work_trace_delta"}
    )
    assert all(event["message"] != "Gemini thought summary." for event in final.run_trace["events"])


def test_agent_service_hides_codex_model_trace_when_summary_disabled(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[
        AIMessage(
            content="Final answer.",
            response_metadata={
                "codex_work_trace": [{
                    "text": "Codex searched web: DeepSeek",
                    "traceType": "tool",
                    "source": "codex",
                }],
                "codex_model_trace": [{
                    "text": "Hidden Codex reasoning summary.",
                    "traceType": "summary",
                    "source": "codex",
                    "data": {"type": "reasoning"},
                }],
            },
        )
    ])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    events = list(service.stream(AgentServiceRequest(
        message="Search.",
        provider="codex-oauth",
        model="gpt-5.5",
        model_options={"effort": "none", "summary": "none"},
        enable_tools=False,
    )))

    work_texts = [
        event.data.get("text")
        for event in events
        if event.event in {"work_trace_item", "work_trace_delta"}
    ]
    final = next(event.data["result"] for event in events if event.event == "final")
    assert "Codex searched web: DeepSeek" in work_texts
    assert "Hidden Codex reasoning summary." not in work_texts
    assert all(event["message"] != "Hidden Codex reasoning summary." for event in final.run_trace["events"])


def test_agent_service_prefers_provider_reasoning_summary(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[
        AIMessage(
            content=[
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Read visible context."}]},
                {"type": "text", "text": "Final answer."},
            ],
            additional_kwargs={"reasoning_content": "Raw hidden reasoning should not be shown."},
            response_metadata={"model_provider": "openai"},
        )
    ])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    events = list(service.stream(AgentServiceRequest(message="Explain.", enable_tools=False)))

    summary_items = [
        event for event in events
        if event.event == "work_trace_item" and event.data.get("traceType") == "summary"
    ]

    assert any(item.data["text"] == "Read visible context." for item in summary_items)
    assert all(item.data.get("text") != "Raw hidden reasoning should not be shown." for item in events)


def test_streaming_model_trace_metadata_becomes_work_trace_delta():
    token = AIMessageChunk(
        content="",
        response_metadata={
            "paper_notes_trace": {
                "delta": "Reading the visible page.",
                "traceType": "summary",
                "source": "codex",
                "data": {"type": "reasoning"},
            }
        },
    )

    events = events_from_langchain_chunk({"type": "messages", "data": (token, {"langgraph_node": "model"})})

    assert len(events) == 1
    assert events[0].event == "work_trace_delta"
    assert events[0].data["traceType"] == "summary"
    assert events[0].data["delta"] == "Reading the visible page."


def test_streaming_raw_reasoning_content_block_is_hidden():
    token = AIMessageChunk(content=[{"type": "reasoning", "reasoning": "Checking page context."}])

    events = events_from_langchain_chunk({"type": "messages", "data": (token, {"langgraph_node": "model"})})

    assert events == []


def test_streaming_raw_thinking_content_block_is_hidden():
    token = AIMessageChunk(content=[{"type": "thinking", "thinking": "Reviewing provider context."}])

    events = events_from_langchain_chunk({"type": "messages", "data": (token, {"langgraph_node": "model"})})

    assert events == []


def test_streaming_reasoning_summary_content_block_becomes_work_trace_item():
    token = AIMessageChunk(content=[{"type": "reasoning", "summary": "Checking page context."}])

    events = events_from_langchain_chunk({"type": "messages", "data": (token, {"langgraph_node": "model"})})

    assert len(events) == 1
    assert events[0].event == "work_trace_item"
    assert events[0].data["traceType"] == "summary"
    assert events[0].data["text"] == "Checking page context."
    assert "reasoning" not in events[0].data["data"]


def test_streaming_reasoning_summary_list_block_becomes_work_trace_item():
    token = AIMessageChunk(content=[{
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "Checking page context."}],
    }])

    events = events_from_langchain_chunk({"type": "messages", "data": (token, {"langgraph_node": "model"})})

    assert len(events) == 1
    assert events[0].event == "work_trace_item"
    assert events[0].data["traceType"] == "summary"
    assert events[0].data["text"] == "Checking page context."
    assert "reasoning" not in events[0].data["data"]


def test_streaming_openai_reasoning_block_text_becomes_summary_work_trace_item():
    token = AIMessageChunk(
        content=[{
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "Checking page context."}],
        }],
        response_metadata={"model_provider": "openai"},
    )
    assert token.content_blocks == [{"type": "reasoning", "reasoning": "Checking page context."}]

    events = events_from_langchain_chunk({"type": "messages", "data": (token, {"langgraph_node": "model"})})

    assert len(events) == 1
    assert events[0].event == "work_trace_item"
    assert events[0].data["traceType"] == "summary"
    assert events[0].data["text"] == "Checking page context."


def test_streaming_tool_call_event_includes_tool_args():
    message = AIMessage(
        content="",
        tool_calls=[{
            "name": "search_notes",
            "args": {"query": "你好", "limit": 3},
            "id": "call-1",
            "type": "tool_call",
        }],
    )

    events = events_from_langchain_chunk({"type": "updates", "data": {"model": {"messages": [message]}}})

    assert len(events) == 1
    assert events[0].event == "work_trace_item"
    assert events[0].data["traceType"] == "tool"
    assert "search_notes" in events[0].data["text"]
    assert '{"query":"你好","limit":3}' in events[0].data["text"]


def test_streaming_update_emits_provider_reasoning_before_tool_call():
    message = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "Need note context first."},
        response_metadata={"model_provider": "deepseek"},
        tool_calls=[{
            "name": "search_notes",
            "args": {"query": "DeepSeek"},
            "id": "call-1",
            "type": "tool_call",
        }],
    )

    events = events_from_langchain_chunk({"type": "updates", "data": {"model": {"messages": [message]}}})

    assert [event.data["traceType"] for event in events] == ["reasoning", "tool"]
    assert events[0].data["text"] == "Need note context first."
    assert "search_notes" in events[1].data["text"]


def test_agent_service_continues_existing_session(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(content="First answer."),
            AIMessage(content="Second answer."),
        ]
    )
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    first = service.run(AgentServiceRequest(message="First question", title="Continuity", enable_tools=False))
    second = service.run(AgentServiceRequest(message="Second question", session_id=first.session_id, enable_tools=False))

    assert second.created_session is False
    assert [message["content"] for message in second.messages] == [
        "First question",
        "First answer.",
        "Second question",
        "Second answer.",
    ]
    assert store.require_session(first.session_id).metadata.message_count == 4


@dataclass
class _UsageMetadata:
    input_tokens: int
    output_tokens: int


def test_agent_service_persists_json_safe_response_metadata(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="Metadata-safe answer.",
                response_metadata={"usage": _UsageMetadata(input_tokens=3, output_tokens=4)},
            )
        ]
    )
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    result = service.run(AgentServiceRequest(message="Hello", enable_tools=False))

    assistant = store.require_session(result.session_id).messages[-1]
    assert assistant["content"] == "Metadata-safe answer."
    assert assistant["metadata"]["response_metadata"]["usage"] == {"input_tokens": 3, "output_tokens": 4}


def test_agent_service_attaches_generated_tool_artifact_to_latest_assistant():
    artifact = {
        "id": "file_1",
        "kind": "text",
        "source": "generated",
        "mimeType": "text/markdown",
        "fileName": "summary.md",
        "url": "/api/media/file_1",
        "downloadUrl": "/api/media/file_1/download",
    }
    messages = [
        {"role": "user", "content": "生成一个 markdown 文件"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"name": "create_file_artifact", "args": {}, "id": "call-1"}],
        },
        {
            "role": "tool",
            "name": "create_file_artifact",
            "tool_call_id": "call-1",
            "content": json.dumps({"success": True, "artifacts": [artifact]}),
        },
        {"role": "assistant", "content": "已生成 summary.md。"},
    ]

    updated = _with_generated_artifacts_on_latest_assistant(messages, start_index=0)

    assert updated[-1]["metadata"]["response_metadata"]["artifacts"] == [artifact]
    assert "metadata" not in updated[1]


def test_agent_service_skips_tools_when_model_cannot_bind_them(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="Plain answer.")])
    tool = StructuredTool.from_function(
        func=lambda query: f"tool result for {query}",
        name="lookup_note",
        description="Look up note text.",
    )
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, tools=[tool], use_default_tools=False)

    result = service.run(AgentServiceRequest(message="Hello", enable_tools=True))

    assert result.response == "Plain answer."
    assert [message["content"] for message in result.messages] == ["Hello", "Plain answer."]


def test_agent_service_uses_attachment_fallback_for_empty_message(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="Read the attachment.")])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    result = service.run(AgentServiceRequest(message="", title="Attachment", enable_tools=False))

    assert result.messages[0]["content"] == ATTACHMENT_ONLY_MESSAGE
    assert result.response == "Read the attachment."


def test_agent_service_request_model_overrides_session_metadata(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="Using requested model.")])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    result = service.run(
        AgentServiceRequest(
            message="Use Claude",
            provider="anthropic",
            model="claude-sonnet-4-6",
            enable_tools=False,
        )
    )

    assert result.session.metadata.provider == "anthropic"
    assert result.session.metadata.model == "claude-sonnet-4-6"


def test_agent_service_context_status_uses_model_profile_and_reserve(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="Context answer.")])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)
    result = service.run(AgentServiceRequest(message="Measure context", enable_tools=False))

    status = service.context_status(session_id=result.session_id, enable_tools=False)

    assert status.provider == "openai"
    assert status.model == "gpt-5.5"
    assert status.context_window == 1_050_000
    assert status.reserve_tokens == 13_000
    assert status.collapse_trigger_tokens == 40_000
    assert status.collapse_trigger_messages == 40
    assert status.compaction_trigger_tokens == 1_037_000
    assert status.remaining_tokens == status.context_window - status.estimated_tokens
    assert status.message_count == 2


def test_agent_service_context_status_reads_latest_actual_usage(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[
        AIMessage(
            content="Usage answer.",
            usage_metadata={"input_tokens": 420_000, "output_tokens": 120, "total_tokens": 420_120},
        )
    ])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)
    result = service.run(AgentServiceRequest(
        message="Measure actual usage",
        enable_tools=False,
        metadata={"requestId": "usage-request"},
    ))

    status = service.context_status(session_id=result.session_id, enable_tools=False)

    assert status.actual_usage_available is True
    assert status.actual_input_tokens == 420_000
    assert status.actual_output_tokens == 120
    assert status.actual_total_tokens == 420_120
    assert status.usage_request_id == ""
    assert status.estimated_tokens > 0


def test_agent_service_compact_session_preserves_recent_turn(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="dense summary")])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)
    session = store.create_session(title="Compact me")
    store.replace_messages(session.metadata.session_id, [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "current question"},
    ])

    result = service.compact_session(session_id=session.metadata.session_id, enable_tools=False)

    assert result.compressed is True
    messages = result.session.messages
    assert messages[0]["role"] == "user"
    assert messages[0]["content"].startswith("[summary]")
    assert "dense summary" in messages[0]["content"]
    assert [message["content"] for message in messages[1:4]] == ["previous question", "previous answer", "current question"]
    assert messages[-1]["role"] == "divider"
    assert messages[-1]["metadata"]["type"] == "context_compaction_marker"
