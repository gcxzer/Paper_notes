from __future__ import annotations

from http import HTTPStatus
import threading
import time

import pytest

from agent_runtime.service import AgentService, AgentServiceRequest, AgentServiceResult
from context_compression import ContextCompressionConfig, ContextCompressor
from agent_sessions import AgentSession, AgentSessionMetadata, AgentSessionStore
from tool_safety import PaperNotesSnapshotManager
from library import write_library
from backend.agent_api import (
    AgentAPIError,
    archive_chat_session,
    branch_chat_session,
    cancel_chat_request,
    compact_chat_session,
    create_chat_session,
    delete_chat_session,
    get_chat_context_status,
    get_chat_progress,
    get_chat_session,
    handle_chat_request,
    handle_chat_stream_request,
    list_chat_tool_approvals,
    cleanup_chat_tool_snapshots,
    list_chat_tool_snapshots,
    list_chat_sessions,
    preview_chat_tool_snapshot,
    rename_chat_session,
    redo_chat_tool_snapshot,
    respond_chat_tool_approval,
    serialize_message,
    serialize_session,
    undo_chat_session,
    undo_chat_tool_snapshot,
    upload_chat_attachment,
    update_chat_session_model,
)
from model_providers import ModelProviderAPIError
from model_providers.types import ModelRequest, ModelResponse, ModelStreamEvent, ToolCall
from tools.paper_notes import create_paper_notes_registry
from tools.registry import ToolDefinition, ToolRegistry
from telemetry.agent_progress import AgentProgressStore
from telemetry.agent_runs import AgentRunCoordinator
from telemetry.debug_logs import DebugRunStore


PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)


class APIErrorProvider:
    name = "openai"

    def __init__(self, error: ModelProviderAPIError) -> None:
        self.error = error
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        raise self.error


class BlockingProvider:
    name = "blocking"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.first_started = threading.Event()
        self.release_first = threading.Event()
        self._lock = threading.Lock()

    def generate(self, request: ModelRequest) -> ModelResponse:
        with self._lock:
            index = len(self.requests)
            self.requests.append(request)
        if index == 0:
            self.first_started.set()
            self.release_first.wait(timeout=2)
        return ModelResponse(content=f"Answer {index + 1}.")


class StreamingReasoningBlockingProvider(BlockingProvider):
    def stream_generate(self, request: ModelRequest, event_sink=None) -> ModelResponse:
        with self._lock:
            index = len(self.requests)
            self.requests.append(request)
        if index == 0:
            self.first_started.set()
            if event_sink is not None:
                event_sink(ModelStreamEvent(type="reasoning_summary_done", text="Checked page context."))
            self.release_first.wait(timeout=2)
        return ModelResponse(content=f"Answer {index + 1}.")


class StreamingReasoningDeltaBlockingProvider(BlockingProvider):
    def stream_generate(self, request: ModelRequest, event_sink=None) -> ModelResponse:
        with self._lock:
            index = len(self.requests)
            self.requests.append(request)
        if index == 0:
            self.first_started.set()
            if event_sink is not None:
                event_sink(ModelStreamEvent(type="reasoning_summary_delta", delta="Checked", text="Checked"))
                event_sink(ModelStreamEvent(type="reasoning_summary_delta", delta=" page context.", text="Checked page context."))
            self.release_first.wait(timeout=2)
        return ModelResponse(content=f"Answer {index + 1}.")


def hermes_test_compressor(config: ContextCompressionConfig) -> ContextCompressor:
    def summary_provider(turns, focus_topic=None, *, previous_summary="", max_output_tokens=None):
        return "## Active Task\ncompact from API\n\n## Goal\nPreserve context."

    return ContextCompressor(config, summary_provider=summary_provider)


def _wait_for_api_pending_approval(service: AgentService, session_id: str) -> dict:
    deadline = time.time() + 2
    while time.time() < deadline:
        approvals = service.list_tool_approvals(session_id=session_id)
        if approvals:
            return approvals[0]
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for pending tool approval.")


def test_serialize_message_hides_provider_replay_metadata():
    serialized = serialize_message({
        "role": "assistant",
        "content": "",
        "codex_reasoning_items": [{"type": "reasoning", "encrypted_content": "opaque"}],
        "codex_message_items": [{"type": "message", "content": []}],
        "reasoning_content": "Visible DeepSeek reasoning.",
        "provider_data": {"response_id": "resp_1"},
        "runTrace": {"status": "completed", "events": []},
        "tool_calls": [{
            "id": "call_1",
            "call_id": "call_1",
            "response_item_id": "fc_1",
            "type": "function",
            "function": {"name": "search_notes", "arguments": "{}"},
        }],
    })

    assert "codex_reasoning_items" not in serialized
    assert "codex_message_items" not in serialized
    assert "provider_data" not in serialized
    assert "reasoning_content" not in serialized
    assert "reasoningContent" not in serialized
    assert serialized["workTrace"]["items"][-1] == {
        "type": "reasoning",
        "text": "Visible DeepSeek reasoning.",
        "source": "deepseek",
    }
    assert serialized["runTrace"]["status"] == "completed"
    assert "call_id" not in serialized["tool_calls"][0]
    assert "response_item_id" not in serialized["tool_calls"][0]


def test_serialize_session_keeps_cancelled_tool_call_work_trace():
    session = AgentSession(
        metadata=AgentSessionMetadata(
            session_id="session-1",
            title="Cancelled",
            created_at="2026-05-15T00:00:00+00:00",
            updated_at="2026-05-15T00:00:01+00:00",
            date_bucket="15_05_2026",
            message_count=2,
        ),
        messages=[
            {"role": "user", "content": "Add a highlight."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "execute_code", "arguments": "{}"},
                }],
                "runTrace": {"status": "cancelled", "events": []},
                "workTrace": {
                    "status": "cancelled",
                    "items": [{"type": "summary", "text": "I inspected the annotation flow.", "source": "provider"}],
                },
            },
        ],
    )

    serialized = serialize_session(session)

    assert serialized["messages"][-1]["role"] == "assistant"
    assert "tool_calls" not in serialized["messages"][-1]
    assert serialized["messages"][-1]["workTrace"]["items"][0]["text"] == "I inspected the annotation flow."


def test_serialize_chat_result_places_deepseek_reasoning_in_work_trace(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([
            ModelResponse(
                content="Final answer.",
                provider_data={"provider": "deepseek", "reasoning_content": "I should answer carefully."},
            )
        ]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    payload = handle_chat_request(
        {
            "message": "Explain this.",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "requestOptions": {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
        },
        service=service,
    )

    assert payload["message"]["workTrace"]["items"][-1] == {
        "type": "reasoning",
        "text": "I should answer carefully.",
        "source": "deepseek",
    }
    assert "reasoningContent" not in payload["messages"][-1]


def test_deepseek_think_mode_off_disables_provider_thinking(tmp_path):
    provider = FakeProvider([ModelResponse(content="No reasoning.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Answer directly.",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "metadata": {"deepseekThinkMode": "off"},
            "requestOptions": {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
        },
        service=service,
    )

    assert provider.requests[0].request_options["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in provider.requests[0].request_options


def test_deepseek_think_mode_high_enables_provider_thinking(tmp_path):
    provider = FakeProvider([ModelResponse(content="Reasoned answer.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Think carefully.",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "metadata": {"deepseekThinkMode": "high"},
        },
        service=service,
    )

    assert provider.requests[0].request_options["thinking"] == {"type": "enabled"}
    assert provider.requests[0].request_options["reasoning_effort"] == "high"


def test_openai_gpt_think_mode_off_disables_reasoning_effort(tmp_path):
    provider = FakeProvider([ModelResponse(content="Direct answer.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Answer directly.",
            "provider": "openai",
            "model": "gpt-5.5",
            "metadata": {"gptThinkMode": "off"},
            "requestOptions": {"reasoning": {"effort": "high", "summary": "auto"}},
        },
        service=service,
    )

    assert provider.requests[0].request_options["reasoning"] == {"effort": "none"}


def test_openai_gpt_think_mode_high_enables_reasoning_summary(tmp_path):
    provider = FakeProvider([ModelResponse(content="Reasoned answer.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Think carefully.",
            "provider": "openai",
            "model": "gpt-5.5",
            "metadata": {"gptThinkMode": "high"},
        },
        service=service,
    )

    assert provider.requests[0].request_options["reasoning"] == {"effort": "high", "summary": "auto"}


def test_gemini_flash_think_off_uses_minimal_level(tmp_path):
    provider = FakeProvider([ModelResponse(content="Done.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Explain this.",
            "provider": "gemini",
            "model": "gemini-3-flash-preview",
            "metadata": {"geminiThinkMode": "off"},
        },
        service=service,
    )

    assert provider.requests[0].request_options["thinkingConfig"] == {"thinkingLevel": "minimal"}


def test_gemini_flash_think_high_includes_thoughts(tmp_path):
    provider = FakeProvider([ModelResponse(content="Done.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Explain this.",
            "provider": "gemini",
            "model": "gemini-3-flash-preview",
            "metadata": {"geminiThinkMode": "high"},
        },
        service=service,
    )

    assert provider.requests[0].request_options["thinkingConfig"] == {
        "thinkingLevel": "high",
        "includeThoughts": True,
    }


def test_gemini_pro_think_off_normalizes_to_high(tmp_path):
    provider = FakeProvider([ModelResponse(content="Done.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Explain this.",
            "provider": "gemini",
            "model": "gemini-3-pro-preview",
            "metadata": {"geminiThinkMode": "off"},
        },
        service=service,
    )

    assert provider.requests[0].request_options["thinkingConfig"] == {
        "thinkingLevel": "high",
        "includeThoughts": True,
    }


def test_anthropic_think_mode_off_disables_thinking(tmp_path):
    provider = FakeProvider([ModelResponse(content="Done.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Explain this.",
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "metadata": {"anthropicThinkMode": "off"},
            "requestOptions": {"output_config": {"effort": "high"}},
        },
        service=service,
    )

    assert provider.requests[0].request_options["thinking"] == {"type": "disabled"}
    assert "output_config" not in provider.requests[0].request_options


def test_anthropic_sonnet_think_medium_uses_adaptive_effort(tmp_path):
    provider = FakeProvider([ModelResponse(content="Done.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Explain this.",
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "metadata": {"anthropicThinkMode": "medium"},
        },
        service=service,
    )

    assert provider.requests[0].request_options["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert provider.requests[0].request_options["output_config"] == {"effort": "medium"}


def test_anthropic_sonnet_rejects_xhigh_to_medium(tmp_path):
    provider = FakeProvider([ModelResponse(content="Done.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Explain this.",
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "metadata": {"anthropicThinkMode": "xhigh"},
        },
        service=service,
    )

    assert provider.requests[0].request_options["output_config"] == {"effort": "medium"}


def test_anthropic_opus_allows_xhigh(tmp_path):
    provider = FakeProvider([ModelResponse(content="Done.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Explain this.",
            "provider": "anthropic",
            "model": "claude-opus-4-7",
            "metadata": {"anthropicThinkMode": "xhigh"},
        },
        service=service,
    )

    assert provider.requests[0].request_options["output_config"] == {"effort": "xhigh"}


def test_anthropic_haiku_does_not_send_think_options(tmp_path):
    provider = FakeProvider([ModelResponse(content="Done.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    handle_chat_request(
        {
            "message": "Explain this.",
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "metadata": {"anthropicThinkMode": "max"},
            "requestOptions": {
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": "max"},
            },
        },
        service=service,
    )

    assert "thinking" not in provider.requests[0].request_options
    assert "output_config" not in provider.requests[0].request_options


def test_serialize_message_normalizes_sandbox_media_links():
    serialized = serialize_message({
        "role": "assistant",
        "content": "[Download generated image](sandbox:/api/media/gen_123/download)",
    })

    assert serialized["text"] == "[Download generated image](/api/media/gen_123/download)"


def test_serialize_session_backfills_missing_run_trace_from_debug_logs(tmp_path):
    session_store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = session_store.create_session(title="Trace backfill")
    session = session_store.replace_messages(session.metadata.session_id, [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Backfilled answer."},
    ])
    debug_store = DebugRunStore(tmp_path / ".paper-notes" / "logs" / "runs")
    debug_store.start_run(request_id="reader-chat-trace", session_id=session.metadata.session_id)
    debug_store.finish_run(
        "reader-chat-trace",
        status="completed",
        session_id=session.metadata.session_id,
        events=[{"type": "model_request", "message": "Calling model provider.", "data": {"turn": 1}}],
        final_message_preview="Backfilled answer.",
    )

    payload = serialize_session(session, debug_store=debug_store)

    trace = payload["messages"][1]["runTrace"]
    assert trace["requestId"] == "reader-chat-trace"
    assert trace["status"] == "completed"
    assert trace["events"][0]["type"] == "model_request"


def test_handle_chat_request_hides_tool_turn_commentary_from_public_messages(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Lookup.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True, "result": "ok"},
        read_only=True,
    ))
    provider = FakeProvider([
        ModelResponse(
            content="Need understand. Read page 9 and maybe render/extract?",
            tool_calls=[ToolCall(id="call_lookup", name="lookup", arguments="{}")],
            finish_reason="tool_calls",
            provider_data={
                "work_trace_items": [{
                    "type": "commentary",
                    "text": "Need understand. Read page 9 and maybe render/extract?",
                    "source": "provider",
                }],
            },
        ),
        ModelResponse(content="Final answer."),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        default_model="test-model",
    )

    payload = handle_chat_request({
        "requestId": "reader-chat-commentary",
        "message": "Generate an image.",
        "model": "test-model",
    }, service=service)

    assert [message["role"] for message in payload["messages"]] == ["user", "assistant"]
    assert [message["text"] for message in payload["messages"]] == ["Generate an image.", "Final answer."]
    assert all("tool_calls" not in message for message in payload["messages"])
    assert payload["message"]["text"] == "Final answer."
    assert payload["message"]["workTrace"]["items"][0]["text"] == "Need understand. Read page 9 and maybe render/extract?"
    raw_messages = service.session_store.require_session(payload["sessionId"]).messages
    assert any(
        message.get("role") == "assistant"
        and message.get("tool_calls")
        and message.get("content") == "Need understand. Read page 9 and maybe render/extract?"
        for message in raw_messages
    )


def test_handle_chat_request_runs_service_and_serializes_response(tmp_path):
    provider = FakeProvider([ModelResponse(content="Here is the answer.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )

    payload = handle_chat_request({
        "message": "Explain this annotation.",
        "noteId": "note-1",
        "noteTitle": "Attention Paper",
        "currentPage": 3,
        "selectionText": "scaled dot-product attention",
    }, service=service)

    assert payload["completed"] is True
    assert payload["response"] == "Here is the answer."
    assert payload["message"]["text"] == "Here is the answer."
    assert payload["session"]["title"] == "Explain this annotation."
    assert payload["session"]["noteId"] == "note-1"
    assert payload["session"]["provider"] == "fake"
    assert [message["role"] for message in payload["messages"]] == ["user", "assistant"]
    assert "Current page: 3" in provider.requests[0].instructions
    assert "scaled dot-product attention" in provider.requests[0].instructions


def test_handle_chat_request_surfaces_openai_quota_error(tmp_path):
    provider = APIErrorProvider(ModelProviderAPIError(
        "You exceeded your current quota.",
        status_code=429,
        body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}},
        provider_data={"provider": "openai", "api_error_code": "insufficient_quota"},
    ))
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="gpt-test",
    )

    with pytest.raises(AgentAPIError) as exc_info:
        handle_chat_request({"message": "Hello", "provider": "openai", "model": "gpt-test"}, service=service)

    assert exc_info.value.status == HTTPStatus.BAD_GATEWAY
    assert exc_info.value.code == "model_provider_api"
    assert "quota or credits are exhausted" in exc_info.value.message


def test_handle_chat_request_sanitizes_openai_auth_error(tmp_path):
    provider = APIErrorProvider(ModelProviderAPIError(
        "Incorrect API key provided.",
        status_code=401,
        body={"error": {"code": "invalid_api_key", "message": "Incorrect API key provided."}},
        provider_data={"provider": "openai", "api_error_code": "invalid_api_key"},
    ))
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="gpt-test",
    )

    with pytest.raises(AgentAPIError) as exc_info:
        handle_chat_request({"message": "Hello", "provider": "openai", "model": "gpt-test"}, service=service)

    assert exc_info.value.message == "OpenAI credential was rejected. Check or replace it in Settings."
    assert "api key" not in exc_info.value.message.lower()


def test_handle_chat_request_normalizes_sandbox_media_links_in_final_payload(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="[Download generated image](sandbox:/api/media/gen_abc/download)"),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )

    payload = handle_chat_request({"message": "Make image.", "model": "test-model"}, service=service)

    assert "sandbox:" not in payload["response"]
    assert payload["message"]["text"] == "[Download generated image](/api/media/gen_abc/download)"
    assert payload["messages"][-1]["text"] == "[Download generated image](/api/media/gen_abc/download)"


def test_handle_chat_request_edits_latest_user_message(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="First answer."),
        ModelResponse(content="Edited answer."),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )

    first = handle_chat_request({"message": "First prompt.", "model": "test-model"}, service=service)
    edited = handle_chat_request({
        "message": "Edited prompt.",
        "sessionId": first["sessionId"],
        "model": "test-model",
        "editLatestUserMessage": True,
    }, service=service)

    assert [message["role"] for message in edited["messages"]] == ["user", "assistant"]
    assert [message["text"] for message in edited["messages"]] == ["Edited prompt.", "Edited answer."]
    assert edited["message"]["runTrace"]["status"] == "completed"


def test_handle_chat_request_uses_hermes_iteration_budget_defaults(tmp_path):
    class CapturingService(AgentService):
        def __init__(self) -> None:
            super().__init__(
                model_provider=FakeProvider([ModelResponse(content="ok")]),
                session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
                tool_registry=ToolRegistry(),
                default_model="test-model",
            )
            self.last_request: AgentServiceRequest | None = None

        def run(self, request: AgentServiceRequest) -> AgentServiceResult:
            self.last_request = request
            session = self.session_store.create_session(title=request.title, model=request.model or "test-model")
            assistant = {"role": "assistant", "content": "ok"}
            return AgentServiceResult(
                session_id=session.metadata.session_id,
                session=session,
                completed=True,
                response="ok",
                messages=[assistant],
                created_session=True,
            )

    default_service = CapturingService()
    handle_chat_request({"message": "hello"}, service=default_service)
    assert default_service.last_request is not None
    assert default_service.last_request.max_turns == 90
    assert default_service.last_request.summarize_on_max_turns is True
    assert default_service.last_request.budget_warnings_enabled is True
    assert default_service.last_request.stream_events_enabled is False

    capped_service = CapturingService()
    handle_chat_request({
        "message": "hello",
        "maxTurns": 999,
        "summarizeOnMaxTurns": False,
        "budgetWarningsEnabled": False,
    }, service=capped_service)
    assert capped_service.last_request is not None
    assert capped_service.last_request.max_turns == 200
    assert capped_service.last_request.summarize_on_max_turns is False
    assert capped_service.last_request.budget_warnings_enabled is False


def test_upload_chat_attachment_returns_media_artifact(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([ModelResponse(content="ok")]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
    )

    payload = upload_chat_attachment(
        {"data": PNG_DATA_URL, "fileName": "tiny.png", "sessionId": "session-1"},
        service=service,
    )

    artifact = payload["artifact"]
    assert artifact["id"]
    assert artifact["mimeType"] == "image/png"
    assert artifact["url"] == f"/api/media/{artifact['id']}"


def test_upload_chat_attachment_accepts_file_artifact(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([ModelResponse(content="ok")]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
    )

    payload = upload_chat_attachment(
        {"data": "data:text/plain;base64,SGVsbG8=", "fileName": "note.txt", "sessionId": "session-1"},
        service=service,
    )

    artifact = payload["artifact"]
    assert artifact["kind"] == "text"
    assert artifact["mimeType"] == "text/plain"
    assert artifact["size"] == 5


def test_upload_chat_attachment_accepts_code_file_artifact(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([ModelResponse(content="ok")]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
    )

    payload = upload_chat_attachment(
        {"data": "data:application/octet-stream;base64,Y29uc3QgdmFsdWUgPSA0MjsK", "fileName": "sample.ts", "sessionId": "session-1"},
        service=service,
    )

    artifact = payload["artifact"]
    assert artifact["kind"] == "text"
    assert artifact["mimeType"] == "text/plain"
    assert artifact["metadata"]["detectedText"] is True


def test_handle_chat_request_records_progress_events(tmp_path):
    provider = FakeProvider([ModelResponse(content="Here is the answer.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )
    progress_store = AgentProgressStore()

    payload = handle_chat_request({
        "requestId": "req-1",
        "message": "Explain this annotation.",
    }, service=service, progress_store=progress_store)
    progress = get_chat_progress({"id": ["req-1"]}, progress_store=progress_store)

    assert payload["completed"] is True
    assert progress["status"] == "completed"
    assert progress["stage"] == "completed"
    assert [event["type"] for event in progress["events"]] == [
        "running",
        "model_request",
        "model_response",
        "completed",
    ]


def test_handle_chat_stream_request_emits_model_delta_and_final_events(tmp_path):
    class StreamingProvider(FakeProvider):
        def stream_generate(self, request: ModelRequest, event_sink=None) -> ModelResponse:
            self.requests.append(request)
            if event_sink is not None:
                event_sink(ModelStreamEvent(type="text_delta", delta="Hel", text="Hel"))
                event_sink(ModelStreamEvent(type="text_delta", delta="lo", text="Hello"))
            return self.responses.pop(0)

    provider = StreamingProvider([ModelResponse(content="Hello")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )
    progress_store = AgentProgressStore()
    stream_events = []

    handle_chat_stream_request(
        {"requestId": "req-stream", "message": "Hi"},
        send_event=lambda name, payload: stream_events.append((name, payload)),
        service=service,
        progress_store=progress_store,
    )

    names = [name for name, _ in stream_events]
    assert names[0] == "start"
    assert [payload["delta"] for name, payload in stream_events if name == "model_delta"] == ["Hel", "lo"]
    assert names[-2:] == ["final", "done"]
    assert stream_events[-2][1]["response"] == "Hello"
    assert progress_store.get("req-stream")["status"] == "completed"
    assert provider.requests[0].model == "test-model"


def test_handle_chat_stream_request_emits_work_trace_events_and_final_work_trace(tmp_path):
    class StreamingProvider(FakeProvider):
        def stream_generate(self, request: ModelRequest, event_sink=None) -> ModelResponse:
            self.requests.append(request)
            if event_sink is not None:
                event_sink(ModelStreamEvent(type="reasoning_summary_done", text="Checked note metadata."))
            return self.responses.pop(0)

    provider = StreamingProvider([ModelResponse(
        content="Done",
        provider_data={"work_trace_items": [{"type": "summary", "text": "Checked note metadata.", "source": "provider"}]},
    )])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )
    progress_store = AgentProgressStore()
    stream_events = []

    handle_chat_stream_request(
        {"requestId": "req-work", "message": "Hi"},
        send_event=lambda name, payload: stream_events.append((name, payload)),
        service=service,
        progress_store=progress_store,
    )

    assert "work_trace_item" in [name for name, _ in stream_events]
    progress = progress_store.get("req-work")
    assert progress["workTrace"]["items"][0]["text"] == "Checked note metadata."
    final_payload = [payload for name, payload in stream_events if name == "final"][0]
    assert final_payload["message"]["workTrace"]["items"][0]["text"] == "Checked note metadata."
    assert "model_request" not in [item["type"] for item in final_payload["message"]["workTrace"]["items"]]


def test_chat_stream_disconnect_does_not_stop_background_run(tmp_path):
    class SlowProvider(FakeProvider):
        def generate(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            time.sleep(0.2)
            return self.responses.pop(0)

    provider = SlowProvider([ModelResponse(content="Still finished.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )
    progress_store = AgentProgressStore()
    stream_events = []

    handle_chat_stream_request(
        {"requestId": "req-disconnect", "message": "Keep going"},
        send_event=lambda name, payload: stream_events.append((name, payload)) or len(stream_events) < 2,
        service=service,
        progress_store=progress_store,
    )

    assert stream_events[0][0] == "start"
    assert _wait_for(lambda: (progress_store.get("req-disconnect") or {}).get("status") == "completed")
    session_id = stream_events[0][1]["sessionId"]
    session = service.session_store.require_session(session_id)
    assert session.messages[-1]["role"] == "assistant"
    assert "Still finished." in session.messages[-1]["content"]


def test_tool_snapshot_undo_api_restores_file(tmp_path):
    library_path = tmp_path / "notes.json"
    html_dir = tmp_path / "Paper-html"
    annotations_dir = tmp_path / "Paper-annotations"
    html_dir.mkdir(parents=True)
    html_path = html_dir / "note-1.html"
    html_path.write_text(
        "<html><body><main class=\"note-body\"><h2>Existing</h2><p>Old.</p></main></body></html>",
        encoding="utf-8",
    )
    write_library({
        "notes": [{
            "id": "note-1",
            "title": "Paper",
            "htmlHref": "resources/Paper-html/note-1.html",
        }],
    }, library_path)
    service = AgentService(
        model_provider=FakeProvider([
            ModelResponse(
                content=None,
                tool_calls=[ToolCall(
                    id="call_api_restore",
                    name="append_note_section",
                    arguments='{"note_id":"note-1","heading":"Undo API","html":"<p>temporary</p>"}',
                )],
                finish_reason="tool_calls",
            ),
            ModelResponse(content="Updated."),
        ]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=create_paper_notes_registry(library_path=library_path, html_dir=html_dir),
        tool_snapshot_manager=PaperNotesSnapshotManager(
            tmp_path / ".paper-notes" / "snapshots",
            project_root=tmp_path,
            notes_path=library_path,
            html_dir=html_dir,
            annotations_dir=annotations_dir,
        ),
    )

    payload = handle_chat_request({"message": "Write temp.", "model": "test-model"}, service=service)
    snapshot = next(event["data"]["snapshot"] for event in payload["events"] if event["type"] == "tool_result")
    assert payload["messages"][-1]["toolActivity"][0]["snapshotId"] == snapshot["snapshotId"]
    assert payload["messages"][-1]["toolActivity"][0]["noteId"] == "note-1"
    assert payload["messages"][-1]["toolActivity"][0]["toolMessage"] == "Updated HTML note section using append."
    assert "Undo API" in html_path.read_text(encoding="utf-8")

    preview = preview_chat_tool_snapshot({
        "sessionId": [payload["sessionId"]],
        "snapshotId": [snapshot["snapshotId"]],
    }, service=service)

    restored = undo_chat_tool_snapshot({
        "sessionId": payload["sessionId"],
        "snapshotId": snapshot["snapshotId"],
    }, service=service)

    assert preview["success"] is True
    assert preview["files"][0]["path"] == "Paper-html/note-1.html"
    assert "+<h2 id=\"undo-api\">Undo API</h2>" in preview["files"][0]["diff"]
    assert restored["success"] is True
    assert "Undo API" not in html_path.read_text(encoding="utf-8")

    redone = redo_chat_tool_snapshot({
        "sessionId": payload["sessionId"],
        "snapshotId": snapshot["snapshotId"],
    }, service=service)

    assert redone["success"] is True
    assert "Undo API" in html_path.read_text(encoding="utf-8")


def test_tool_snapshot_api_lists_cleans_and_conflicts(tmp_path):
    library_path = tmp_path / "notes.json"
    html_dir = tmp_path / "Paper-html"
    annotations_dir = tmp_path / "Paper-annotations"
    html_dir.mkdir(parents=True)
    html_path = html_dir / "note-1.html"
    html_path.write_text(
        "<html><body><main class=\"note-body\"><h2>Existing</h2><p>Old.</p></main></body></html>",
        encoding="utf-8",
    )
    write_library({
        "notes": [{
            "id": "note-1",
            "title": "Paper",
            "htmlHref": "resources/Paper-html/note-1.html",
        }],
    }, library_path)
    service = AgentService(
        model_provider=FakeProvider([
            ModelResponse(
                content=None,
                tool_calls=[ToolCall(
                    id="call_conflict",
                    name="append_note_section",
                    arguments='{"note_id":"note-1","heading":"Conflict","html":"<p>temporary</p>"}',
                )],
                finish_reason="tool_calls",
            ),
            ModelResponse(content="Updated."),
        ]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=create_paper_notes_registry(library_path=library_path, html_dir=html_dir),
        tool_snapshot_manager=PaperNotesSnapshotManager(
            tmp_path / ".paper-notes" / "snapshots",
            project_root=tmp_path,
            notes_path=library_path,
            html_dir=html_dir,
            annotations_dir=annotations_dir,
        ),
    )
    payload = handle_chat_request({"message": "Write temp.", "model": "test-model"}, service=service)
    snapshot_id = payload["messages"][-1]["toolActivity"][0]["snapshotId"]
    listed = list_chat_tool_snapshots({"sessionId": [payload["sessionId"]]}, service=service)
    html_path.write_text(html_path.read_text(encoding="utf-8") + "\n<p>newer user edit</p>", encoding="utf-8")

    with pytest.raises(AgentAPIError) as conflict:
        undo_chat_tool_snapshot({"sessionId": payload["sessionId"], "snapshotId": snapshot_id}, service=service)
    forced = undo_chat_tool_snapshot({
        "sessionId": payload["sessionId"],
        "snapshotId": snapshot_id,
        "force": True,
    }, service=service)
    cleanup = cleanup_chat_tool_snapshots({
        "sessionId": payload["sessionId"],
        "keepPerSession": 0,
    }, service=service)

    assert listed["snapshots"][0]["snapshotId"] == snapshot_id
    assert conflict.value.status == HTTPStatus.CONFLICT
    assert conflict.value.code == "snapshot_conflict"
    assert forced["forced"] is True
    assert cleanup["deletedCount"] == 1


def test_handle_chat_request_readonly_write_mode_hides_mutating_tools(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="read_tool",
        description="Read.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="write_tool",
        description="Write.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        mutating=True,
        risk="write",
    ))
    provider = FakeProvider([ModelResponse(content="Readonly.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
    )

    handle_chat_request({
        "message": "Hello",
        "model": "test-model",
        "writeToolMode": "readonly",
    }, service=service)

    assert [tool["function"]["name"] for tool in provider.requests[0].tools] == ["read_tool"]


def test_handle_chat_request_applies_disabled_tools_and_per_tool_modes(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="read_tool",
        description="Read.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="write_tool",
        description="Write.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        mutating=True,
        risk="write",
    ))
    registry.register(ToolDefinition(
        name="other_write_tool",
        description="Write too.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        mutating=True,
        risk="write",
    ))
    provider = FakeProvider([ModelResponse(content="Filtered.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
    )

    handle_chat_request({
        "message": "Hello",
        "model": "test-model",
        "disabledTools": ["read_tool"],
        "toolWriteModes": {"other_write_tool": "readonly"},
    }, service=service)

    assert [tool["function"]["name"] for tool in provider.requests[0].tools] == ["write_tool"]


def test_chat_tool_approval_api_allows_waiting_write(tmp_path):
    tool_calls: list[dict] = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="write_tool",
        description="Write.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: tool_calls.append(args) or {"success": True},
        mutating=True,
        risk="write",
    ))
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="call_api_approval", name="write_tool", arguments="{}")],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Done."),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
    )
    session = create_chat_session({"title": "Approval"}, service=service)["session"]
    holder: dict[str, object] = {}
    progress = AgentProgressStore()

    def run_request() -> None:
        holder["payload"] = handle_chat_request({
            "requestId": "req-api-approval",
            "sessionId": session["id"],
            "message": "Write.",
            "model": "test-model",
            "writeToolMode": "ask",
        }, service=service, progress_store=progress, run_coordinator=AgentRunCoordinator())

    thread = threading.Thread(target=run_request)
    thread.start()
    approval = _wait_for_api_pending_approval(service, session["id"])
    listed = list_chat_tool_approvals({"sessionId": [session["id"]]}, service=service)
    response = respond_chat_tool_approval({
        "approvalId": approval["approvalId"],
        "action": "allow_once",
    }, service=service)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert listed["approvals"][0]["approvalId"] == approval["approvalId"]
    assert response["approval"]["status"] == "allowed"
    assert holder["payload"]["completed"] is True
    assert tool_calls == [{}]


def test_get_chat_progress_returns_unknown_for_unstarted_request():
    progress = get_chat_progress({"id": ["missing"]}, progress_store=AgentProgressStore())

    assert progress["status"] == "unknown"
    assert progress["requestId"] == "missing"


def test_get_chat_context_status_serializes_context_budget(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="gpt-5.5",
    )
    session = create_chat_session({
        "title": "Budget",
        "provider": "codex-oauth",
        "model": "gpt-5.5",
    }, service=service)["session"]
    service.session_store.append_message(session["id"], {
        "role": "user",
        "content": "Summarize context status.",
    })

    payload = get_chat_context_status({
        "sessionId": [session["id"]],
        "provider": ["codex-oauth"],
        "model": ["gpt-5.5"],
    }, service=service)

    assert payload["context"]["provider"] == "codex-oauth"
    assert payload["context"]["model"] == "gpt-5.5"
    assert payload["context"]["contextLength"] == 400_000
    assert payload["context"]["tokensUsed"] >= payload["context"]["messageTokens"]
    assert payload["context"]["percentFull"] >= 0


def test_compact_chat_session_serializes_context_and_events(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        context_compressor=hermes_test_compressor(ContextCompressionConfig(
            max_estimated_tokens=999_999,
            min_messages=4,
            protect_first_n=1,
            protect_last_n=2,
            tail_token_budget=16,
        )),
    )
    session = create_chat_session({"title": "Compact me", "model": "test-model"}, service=service)["session"]
    for index in range(8):
        service.session_store.append_message(session["id"], {"role": "user", "content": f"old user {index} " + ("x" * 240)})
        service.session_store.append_message(session["id"], {"role": "assistant", "content": f"old answer {index} " + ("y" * 240)})

    payload = compact_chat_session({
        "sessionId": session["id"],
        "focus": "current paper",
        "model": "test-model",
    }, service=service)

    assert payload["compressed"] is True
    assert payload["context"]["summaryAvailable"] is True
    assert payload["context"]["compressionCount"] == 1
    assert [event["type"] for event in payload["events"]][:2] == ["context_compressing", "context_compressed"]
    assert payload["message"]["role"] == "divider"
    assert payload["message"]["metadata"]["type"] == "context_compaction_marker"
    assert "Context compacted" in payload["message"]["text"]


def test_handle_chat_request_reuses_existing_session(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="First answer."),
        ModelResponse(content="Second answer."),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    first = handle_chat_request({"message": "First", "model": "test-model"}, service=service)

    second = handle_chat_request({
        "message": "Second",
        "sessionId": first["sessionId"],
        "model": "test-model",
    }, service=service)

    assert second["createdSession"] is False
    assert [message["content"] for message in second["messages"]] == [
        "First",
        "First answer.",
        "Second",
        "Second answer.",
    ]


def test_same_session_chat_requests_run_fifo(tmp_path):
    provider = BlockingProvider()
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    progress_store = AgentProgressStore()
    run_coordinator = AgentRunCoordinator()
    session = create_chat_session({"title": "Queue"}, service=service)["session"]
    results: dict[str, dict] = {}
    errors: list[BaseException] = []

    def run_chat(key: str, message: str, request_id: str) -> None:
        try:
            results[key] = handle_chat_request(
                {"requestId": request_id, "sessionId": session["id"], "message": message, "model": "test-model"},
                service=service,
                progress_store=progress_store,
                run_coordinator=run_coordinator,
            )
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=run_chat, args=("first", "First", "req-first"))
    second = threading.Thread(target=run_chat, args=("second", "Second", "req-second"))
    first.start()
    assert provider.first_started.wait(timeout=1)
    second.start()
    assert _wait_for(lambda: (progress_store.get("req-second") or {}).get("status") == "queued")

    provider.release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert errors == []
    assert results["first"]["response"] == "Answer 1."
    assert results["second"]["response"] == "Answer 2."
    assert len(provider.requests) == 2
    visible_contents = [
        message["content"]
        for message in provider.requests[1].messages
        if not str(message.get("content") or "").startswith("# Runtime context")
    ]
    assert visible_contents == [
        "First",
        "Answer 1.",
        "Second",
    ]


def test_queued_chat_request_can_be_cancelled(tmp_path):
    provider = BlockingProvider()
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    progress_store = AgentProgressStore()
    run_coordinator = AgentRunCoordinator()
    session = create_chat_session({"title": "Queue"}, service=service)["session"]
    results: dict[str, dict] = {}

    first = threading.Thread(target=lambda: results.setdefault(
        "first",
        handle_chat_request(
            {"requestId": "req-first", "sessionId": session["id"], "message": "First", "model": "test-model"},
            service=service,
            progress_store=progress_store,
            run_coordinator=run_coordinator,
        ),
    ))
    second = threading.Thread(target=lambda: results.setdefault(
        "second",
        handle_chat_request(
            {"requestId": "req-second", "sessionId": session["id"], "message": "Second", "model": "test-model"},
            service=service,
            progress_store=progress_store,
            run_coordinator=run_coordinator,
        ),
    ))
    first.start()
    assert provider.first_started.wait(timeout=1)
    second.start()
    assert _wait_for(lambda: (progress_store.get("req-second") or {}).get("status") == "queued")

    cancel = cancel_chat_request(
        {"requestId": "req-second"},
        progress_store=progress_store,
        run_coordinator=run_coordinator,
    )
    second.join(timeout=2)

    assert cancel["cancelled"] is True
    assert results["second"]["cancelled"] is True
    assert len(provider.requests) == 1

    provider.release_first.set()
    first.join(timeout=2)
    assert results["first"]["completed"] is True


def test_active_chat_request_can_be_soft_cancelled(tmp_path):
    provider = BlockingProvider()
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    progress_store = AgentProgressStore()
    run_coordinator = AgentRunCoordinator()
    session = create_chat_session({"title": "Cancel"}, service=service)["session"]
    results: dict[str, dict] = {}

    thread = threading.Thread(target=lambda: results.setdefault(
        "chat",
        handle_chat_request(
            {"requestId": "req-active", "sessionId": session["id"], "message": "First", "model": "test-model"},
            service=service,
            progress_store=progress_store,
            run_coordinator=run_coordinator,
        ),
    ))
    thread.start()
    assert provider.first_started.wait(timeout=1)

    cancel = cancel_chat_request(
        {"requestId": "req-active"},
        progress_store=progress_store,
        run_coordinator=run_coordinator,
    )
    assert cancel["cancelled"] is True
    assert cancel["status"] == "cancelling"
    assert progress_store.get("req-active")["status"] == "cancelling"

    provider.release_first.set()
    thread.join(timeout=2)

    assert results["chat"]["cancelled"] is True
    assert results["chat"]["error"] == "cancelled"
    assert [message["text"] for message in results["chat"]["messages"]] == ["First"]
    assert progress_store.get("req-active")["status"] == "cancelled"


def test_cancelled_stream_request_returns_partial_work_trace(tmp_path):
    provider = StreamingReasoningBlockingProvider()
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    progress_store = AgentProgressStore()
    run_coordinator = AgentRunCoordinator()
    session = create_chat_session({"title": "Cancel"}, service=service)["session"]
    results: dict[str, dict] = {}

    thread = threading.Thread(target=lambda: results.setdefault(
        "chat",
        handle_chat_request(
            {
                "requestId": "req-stream-cancel",
                "sessionId": session["id"],
                "message": "First",
                "model": "test-model",
                "streamEventsEnabled": True,
            },
            service=service,
            progress_store=progress_store,
            run_coordinator=run_coordinator,
        ),
    ))
    thread.start()
    assert provider.first_started.wait(timeout=1)

    cancel_chat_request(
        {"requestId": "req-stream-cancel"},
        progress_store=progress_store,
        run_coordinator=run_coordinator,
    )
    provider.release_first.set()
    thread.join(timeout=2)

    assert results["chat"]["cancelled"] is True
    assert results["chat"]["message"]["workTrace"]["items"][0]["text"] == "Checked page context."
    reloaded = get_chat_session({"id": [session["id"]]}, service=service)["session"]
    assert reloaded["messages"][-1]["role"] == "assistant"
    assert reloaded["messages"][-1]["workTrace"]["items"][0]["text"] == "Checked page context."


def test_cancelled_stream_request_persists_partial_work_trace_delta(tmp_path):
    provider = StreamingReasoningDeltaBlockingProvider()
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    progress_store = AgentProgressStore()
    run_coordinator = AgentRunCoordinator()
    session = create_chat_session({"title": "Cancel"}, service=service)["session"]
    results: dict[str, dict] = {}

    thread = threading.Thread(target=lambda: results.setdefault(
        "chat",
        handle_chat_request(
            {
                "requestId": "req-stream-delta-cancel",
                "sessionId": session["id"],
                "message": "First",
                "model": "test-model",
                "streamEventsEnabled": True,
            },
            service=service,
            progress_store=progress_store,
            run_coordinator=run_coordinator,
        ),
    ))
    thread.start()
    assert provider.first_started.wait(timeout=1)

    progress = get_chat_progress({"requestId": ["req-stream-delta-cancel"]}, progress_store=progress_store)
    assert progress["workTrace"]["items"][0]["text"] == "Checked page context."

    cancel_chat_request(
        {"requestId": "req-stream-delta-cancel"},
        progress_store=progress_store,
        run_coordinator=run_coordinator,
    )
    provider.release_first.set()
    thread.join(timeout=2)

    assert results["chat"]["cancelled"] is True
    assert results["chat"]["message"]["workTrace"]["items"][0]["text"] == "Checked page context."
    reloaded = get_chat_session({"id": [session["id"]]}, service=service)["session"]
    assert reloaded["messages"][-1]["workTrace"]["items"][0]["text"] == "Checked page context."


def test_cancel_chat_request_requires_request_or_session_id():
    with pytest.raises(AgentAPIError) as error:
        cancel_chat_request({})

    assert error.value.status == HTTPStatus.BAD_REQUEST
    assert error.value.code == "run_id_required"


def test_cancel_chat_request_is_idempotent_for_unknown_run():
    result = cancel_chat_request(
        {"requestId": "missing"},
        progress_store=AgentProgressStore(),
        run_coordinator=AgentRunCoordinator(),
    )

    assert result == {
        "cancelled": False,
        "status": "not_found",
        "requestId": "missing",
        "sessionId": "",
    }


def test_list_and_get_chat_sessions(tmp_path):
    provider = FakeProvider([ModelResponse(content="Answer.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    chat = handle_chat_request({"message": "Hello", "title": "Session title", "model": "test-model"}, service=service)

    listed = list_chat_sessions(service=service)
    loaded = get_chat_session({"id": [chat["sessionId"]]}, service=service)

    assert listed["sessions"][0]["id"] == chat["sessionId"]
    assert listed["sessions"][0]["title"] == "Session title"
    assert loaded["session"]["messages"][0]["text"] == "Hello"


def test_create_rename_archive_and_delete_chat_session(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    created = create_chat_session(
        {"title": "Draft", "noteId": "note-1", "provider": "openai", "model": "test-model"},
        service=service,
    )
    renamed = rename_chat_session({"sessionId": created["session"]["id"], "title": "Renamed"}, service=service)
    archived = archive_chat_session({"sessionId": created["session"]["id"], "archived": True}, service=service)
    visible = list_chat_sessions(service=service)
    all_sessions = list_chat_sessions({"includeArchived": ["true"]}, service=service)
    deleted = delete_chat_session({"sessionId": created["session"]["id"]}, service=service)

    assert created["session"]["title"] == "Draft"
    assert created["session"]["noteId"] == "note-1"
    assert created["session"]["provider"] == "openai"
    assert renamed["session"]["title"] == "Renamed"
    assert archived["session"]["archived"] is True
    assert visible["sessions"] == []
    assert all_sessions["sessions"][0]["id"] == created["session"]["id"]
    assert deleted["deleted"] is True
    assert service.session_store.get_session(created["session"]["id"]) is None


def test_update_chat_session_model_updates_current_session_only(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    created = create_chat_session({"title": "Draft", "provider": "openai", "model": "gpt-5.4"}, service=service)

    updated = update_chat_session_model(
        {
            "sessionId": created["session"]["id"],
            "provider": "codex-oauth",
            "model": "gpt-5.5",
            "metadata": {"deepseekThinkMode": "max"},
        },
        service=service,
    )

    assert updated["session"]["provider"] == "codex-oauth"
    assert updated["session"]["model"] == "gpt-5.5"
    assert updated["session"]["metadata"]["deepseekThinkMode"] == "max"
    assert service.session_store.require_session(created["session"]["id"]).metadata.provider == "codex-oauth"
    assert service.session_store.require_session(created["session"]["id"]).metadata.metadata["deepseekThinkMode"] == "max"


def test_update_chat_session_model_saves_gpt_think_mode(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    created = create_chat_session({"title": "Draft", "provider": "openai", "model": "gpt-5.5"}, service=service)

    updated = update_chat_session_model(
        {
            "sessionId": created["session"]["id"],
            "provider": "openai",
            "model": "gpt-5.5",
            "metadata": {"gptThinkMode": "xhigh"},
        },
        service=service,
    )

    assert updated["session"]["metadata"]["gptThinkMode"] == "xhigh"
    assert service.session_store.require_session(created["session"]["id"]).metadata.metadata["gptThinkMode"] == "xhigh"


def test_update_chat_session_model_rejects_unsupported_gpt_think_mode(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    created = create_chat_session({"title": "Draft", "provider": "openai", "model": "gpt-5.5"}, service=service)

    updated = update_chat_session_model(
        {
            "sessionId": created["session"]["id"],
            "provider": "openai",
            "model": "gpt-5.5",
            "metadata": {"gptThinkMode": "minimal"},
        },
        service=service,
    )

    assert updated["session"]["metadata"]["gptThinkMode"] == "off"


def test_update_chat_session_model_saves_gemini_flash_think_mode(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    created = create_chat_session({"title": "Draft", "provider": "gemini", "model": "gemini-3-flash-preview"}, service=service)

    updated = update_chat_session_model(
        {
            "sessionId": created["session"]["id"],
            "provider": "gemini",
            "model": "gemini-3-flash-preview",
            "metadata": {"geminiThinkMode": "medium"},
        },
        service=service,
    )

    assert updated["session"]["metadata"]["geminiThinkMode"] == "medium"
    assert service.session_store.require_session(created["session"]["id"]).metadata.metadata["geminiThinkMode"] == "medium"


def test_update_chat_session_model_normalizes_gemini_pro_think_mode(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    created = create_chat_session({"title": "Draft", "provider": "gemini", "model": "gemini-3-pro-preview"}, service=service)

    updated = update_chat_session_model(
        {
            "sessionId": created["session"]["id"],
            "provider": "gemini",
            "model": "gemini-3-pro-preview",
            "metadata": {"geminiThinkMode": "medium"},
        },
        service=service,
    )

    assert updated["session"]["metadata"]["geminiThinkMode"] == "high"


def test_update_chat_session_model_rejects_unsupported_deepseek_think_mode(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    created = create_chat_session({"title": "Draft", "provider": "deepseek", "model": "deepseek-v4-pro"}, service=service)

    updated = update_chat_session_model(
        {
            "sessionId": created["session"]["id"],
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "metadata": {"deepseekThinkMode": "medium"},
        },
        service=service,
    )

    assert updated["session"]["metadata"]["deepseekThinkMode"] == "off"


def test_branch_and_undo_chat_session(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="First answer."),
        ModelResponse(content="Second answer."),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    first = handle_chat_request({"message": "First", "model": "test-model"}, service=service)
    handle_chat_request({"message": "Second", "sessionId": first["sessionId"], "model": "test-model"}, service=service)

    branch = branch_chat_session({"sessionId": first["sessionId"], "title": "Branch"}, service=service)
    undone = undo_chat_session({"sessionId": first["sessionId"]}, service=service)

    assert branch["sourceSessionId"] == first["sessionId"]
    assert branch["session"]["id"] != first["sessionId"]
    assert branch["session"]["title"] == "Branch"
    assert [message["text"] for message in branch["session"]["messages"]] == [
        "First",
        "First answer.",
        "Second",
        "Second answer.",
    ]
    assert undone["removedCount"] == 2
    assert [message["text"] for message in undone["session"]["messages"]] == ["First", "First answer."]


def test_session_lifecycle_requires_session_id(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    with pytest.raises(AgentAPIError) as error:
        archive_chat_session({}, service=service)

    assert error.value.status == HTTPStatus.BAD_REQUEST
    assert error.value.code == "session_id_required"


def test_handle_chat_request_requires_message(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    with pytest.raises(AgentAPIError) as error:
        handle_chat_request({"message": ""}, service=service)

    assert error.value.status == HTTPStatus.BAD_REQUEST
    assert error.value.code == "message_required"


def test_get_chat_session_requires_known_session(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    with pytest.raises(AgentAPIError) as error:
        get_chat_session({"id": ["missing"]}, service=service)

    assert error.value.status == HTTPStatus.NOT_FOUND
    assert error.value.code == "session_not_found"


def _wait_for(predicate, *, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False
