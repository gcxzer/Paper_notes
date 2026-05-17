from __future__ import annotations

import base64
import json
import threading
import time

import pytest

from agent_memory import USER_TARGET, LocalMemoryProvider, MemoryManager
from context_compression import SUMMARY_PREFIX, ContextCompressionConfig, ContextCompressor
from agent_runtime.service import AgentService, AgentServiceRequest
from agent_sessions import AgentSessionStore, SessionNotFoundError
from tool_safety import PaperNotesSnapshotManager, ToolApprovalManager
from library import write_library
from media import MediaStore
from model_providers import ModelProviderAPIError
from model_providers.types import ModelRequest, ModelResponse, TokenUsage, ToolCall
from tools.paper_notes import create_paper_notes_registry
from tools.registry import ToolDefinition, ToolRegistry
from tools.generated_images import TOOL_NAME as CREATE_IMAGE_ARTIFACT_TOOL
from tools.code_execution import register_code_execution_tool
from tools.skills import SkillStore, register_skills_tools
from tools.todo import TODO_METADATA_KEY, SessionTodoStore, create_todo_tool_definition


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


class OverflowThenSuccessProvider:
    name = "fake"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            raise ModelProviderAPIError("context length exceeded", status_code=400)
        return ModelResponse(content="Recovered after compression.")


def hermes_test_compressor(config: ContextCompressionConfig) -> ContextCompressor:
    def summary_provider(turns, focus_topic=None, *, current_summary="", max_output_tokens=None):
        if current_summary:
            return f"{current_summary}\n\n## Completed Actions\nUpdated with {len(turns)} new turn(s)."
        return "## Active Task\nlatest task\n\n## Goal\nKeep working from compacted context."

    return ContextCompressor(config, summary_provider=summary_provider)


def _wait_for_pending_approval(service: AgentService, session_id: str) -> dict:
    deadline = time.time() + 2
    while time.time() < deadline:
        approvals = service.list_tool_approvals(session_id=session_id)
        if approvals:
            return approvals[0]
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for pending tool approval.")


def test_agent_service_request_defaults_to_hermes_iteration_budget():
    assert AgentServiceRequest(message="Hello").max_turns == 90


def test_service_creates_session_runs_provider_and_persists_transcript(tmp_path):
    provider = FakeProvider([ModelResponse(content="A short answer.")])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )

    result = service.run(AgentServiceRequest(message="Summarize this.", title="Paper chat"))

    assert result.completed is True
    assert result.created_session is True
    assert result.response == "A short answer."
    assert [message["role"] for message in result.messages] == ["user", "assistant"]
    assert store.require_session(result.session_id).messages[-1]["content"] == "A short answer."
    assert provider.requests[0].model == "test-model"
    assert "Paper Notes" in provider.requests[0].instructions
    assert "# Runtime context" not in provider.requests[0].instructions
    assert provider.requests[0].messages[0]["role"] == "system"
    assert "# Runtime context" in provider.requests[0].messages[0]["content"]
    assert "Current date:" in provider.requests[0].messages[0]["content"]
    assert "Platform: Paper Notes local web app" in provider.requests[0].messages[0]["content"]
    assert provider.requests[0].tools == []
    assert store.require_session(result.session_id).messages[-1]["runTrace"]["status"] == "completed"


def test_service_instructions_include_native_web_search_when_requested(tmp_path):
    provider = FakeProvider([ModelResponse(content="A short answer.")])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )

    service.run(AgentServiceRequest(
        message="Search current web facts.",
        title="Web chat",
        request_options={"_paper_notes_native_web_search": True},
    ))

    assert "# Provider-native web search" in provider.requests[0].instructions
    assert "current or external web facts" in provider.requests[0].instructions


def test_service_hides_custom_web_search_when_native_web_search_requested(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="web_search",
        description="Search web.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="web_search",
        read_only=True,
        risk="read",
    ))
    provider = FakeProvider([ModelResponse(content="A short answer.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        use_memory=False,
        use_session_search=False,
        use_compression=False,
    )

    service.run(AgentServiceRequest(
        message="Search current web facts.",
        title="Web chat",
        enabled_toolsets=["web_search"],
        request_options={"_paper_notes_native_web_search": True},
    ))

    assert all(tool["function"]["name"] != "web_search" for tool in provider.requests[0].tools)


def test_service_edit_latest_user_message_replaces_last_turn(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="First answer."),
        ModelResponse(content="Edited answer."),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )

    first = service.run(AgentServiceRequest(message="First prompt.", title="Paper chat"))
    edited = service.run(AgentServiceRequest(
        message="Edited prompt.",
        session_id=first.session_id,
        edit_latest_user_message=True,
    ))

    assert edited.response == "Edited answer."
    assert [message["role"] for message in edited.messages] == ["user", "assistant"]
    assert [message["content"] for message in edited.messages] == ["Edited prompt.", "Edited answer."]
    assert "First answer." not in str(edited.messages)


def test_service_edit_latest_user_message_requires_existing_user_message(tmp_path):
    provider = FakeProvider([ModelResponse(content="ok")])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )
    session = store.create_session(title="Empty")

    with pytest.raises(ValueError, match="No user message"):
        service.run(AgentServiceRequest(
            message="Edited prompt.",
            session_id=session.metadata.session_id,
            edit_latest_user_message=True,
        ))


def test_service_persists_max_turn_summary_without_summary_prompt(tmp_path):
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="call_1", name="lookup", arguments="{}")],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Stopped with a summary.", finish_reason="stop"),
    ])
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Lookup.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
    ))
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=registry,
        default_model="test-model",
    )

    result = service.run(AgentServiceRequest(message="Use the tool.", max_turns=1))

    persisted = store.require_session(result.session_id).messages
    assert result.completed is False
    assert result.error == "max_turns_exceeded"
    assert result.response == "Stopped with a summary."
    assert provider.requests[1].tools == []
    assert persisted[-1]["content"] == "Stopped with a summary."
    assert persisted[-1]["metadata"]["max_turns_summary"] is True
    assert not any("_max_turns_summary_request" in message for message in persisted)
    assert not any(
        message.get("role") == "user" and "maximum tool-calling iterations" in str(message.get("content", ""))
        for message in persisted
    )


def test_service_persists_incomplete_replay_metadata_for_next_turn(tmp_path):
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
            },
        ),
        ModelResponse(content="Finished.", finish_reason="stop"),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )

    result = service.run(AgentServiceRequest(message="Continue this.", title="Paper chat"))

    persisted = store.require_session(result.session_id).messages
    assert result.completed is True
    assert result.response == "Finished."
    assert persisted[1]["finish_reason"] == "incomplete"
    assert persisted[1]["codex_reasoning_items"][0]["encrypted_content"] == "opaque"
    assert provider.requests[1].messages[-1]["codex_reasoning_items"][0]["encrypted_content"] == "opaque"


def test_service_persists_attachment_metadata_without_base64(tmp_path):
    provider = FakeProvider([ModelResponse(content="I can see it.")])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )
    artifact = service.media_store.create_upload(PNG_DATA_URL, file_name="tiny.png", scope="session-1")

    result = service.run(AgentServiceRequest(message="", attachments=[{"id": artifact.id}], title="Image chat"))

    persisted_user = store.require_session(result.session_id).messages[0]
    assert persisted_user["content"] == ""
    assert persisted_user["attachments"][0]["id"] == artifact.id
    assert "base64" not in json.dumps(persisted_user)
    assert provider.requests[0].request_options["_write_note_media_store"] is service.media_store


def test_service_instructions_prioritize_attached_file_references(tmp_path):
    provider = FakeProvider([ModelResponse(content="It has content.")])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )
    artifact = service.media_store.create_upload(
        "data:text/markdown;base64,IyBSRUFETUUKCkhlbGxv",
        file_name="README.md",
        scope="session-1",
    )

    service.run(AgentServiceRequest(
        message="文件里有内容吗",
        attachments=[{"id": artifact.id}],
        title="Attachment chat",
    ))

    assert "latest message includes file attachments" in provider.requests[0].instructions
    assert "README.md" in provider.requests[0].instructions


def test_service_adds_ephemeral_attachment_context_with_extracted_text(tmp_path):
    provider = FakeProvider([ModelResponse(content="It has content.")])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )
    artifact = service.media_store.create_upload(
        "data:text/markdown;base64,IyBSRUFETUUKCkhlbGxvIGZyb20gYXR0YWNobWVudA==",
        file_name="README.md",
        scope="session-1",
    )

    service.run(AgentServiceRequest(
        message="文件里有内容吗",
        attachments=[{"id": artifact.id}],
        title="Attachment chat",
    ))

    system_messages = [message for message in provider.requests[0].messages if message.get("role") == "system"]
    attachment_context = next(message for message in system_messages if "Latest user attachments" in message.get("content", ""))
    assert "README.md" in attachment_context["content"]
    assert "Hello from attachment" in attachment_context["content"]
    assert "Do not substitute the current paper" in attachment_context["content"]
    assert "quote brief snippets" in attachment_context["content"]
    assert "```md" in attachment_context["content"]


def test_service_exposes_generated_file_tool_only_when_requested(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="Plain answer."),
        ModelResponse(content="File answer."),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        default_model="test-model",
    )

    service.run(AgentServiceRequest(message="Just chat."))
    service.run(AgentServiceRequest(
        message="Create a markdown file.",
        file_generation={"enabled": True, "format": "markdown"},
    ))

    first_tools = [tool.get("function", {}).get("name") for tool in provider.requests[0].tools]
    second_tools = [tool.get("function", {}).get("name") for tool in provider.requests[1].tools]
    assert "create_file_artifact" not in first_tools
    assert "create_file_artifact" in second_tools
    assert provider.requests[1].request_options["_paper_notes_file_generation"]["format"] == "markdown"
    assert "Create a downloadable file" in provider.requests[1].instructions


def test_service_generated_file_tool_artifact_is_returned_and_persisted(tmp_path):
    provider = FakeProvider([
        ModelResponse(
            content="",
            tool_calls=[ToolCall(
                id="call_file",
                name="create_file_artifact",
                arguments=json.dumps({
                    "file_name": "summary.md",
                    "mime_type": "text/markdown",
                    "content": "# Summary\nGenerated content.",
                }),
            )],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Created the markdown file."),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        default_model="test-model",
    )

    result = service.run(AgentServiceRequest(
        message="Create a markdown file.",
        file_generation={"enabled": True, "format": "markdown"},
    ))

    assert result.completed is True
    assert len(result.artifacts) == 1
    assert result.artifacts[0]["fileName"] == "summary.md"
    persisted = store.require_session(result.session_id).messages
    assert persisted[-1]["artifacts"][0]["fileName"] == "summary.md"
    assert service.media_store.read_bytes(result.artifacts[0]["id"]).decode("utf-8").startswith("# Summary")


def test_service_generated_file_tool_uses_requested_format_over_model_args(tmp_path):
    provider = FakeProvider([
        ModelResponse(
            content="",
            tool_calls=[ToolCall(
                id="call_file",
                name="create_file_artifact",
                arguments=json.dumps({
                    "file_name": "deepseek-v4-note.txt",
                    "mime_type": "text/plain",
                    "content": "Generated content.",
                }),
            )],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Created the markdown file."),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        default_model="test-model",
    )

    result = service.run(AgentServiceRequest(
        message="Create a markdown file.",
        file_generation={"enabled": True, "format": "markdown"},
    ))

    assert result.artifacts[0]["fileName"] == "deepseek-v4-note.md"
    assert result.artifacts[0]["mimeType"] == "text/markdown"


def test_service_exposes_generated_image_tool_only_when_requested(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="Plain answer."),
        ModelResponse(content="Image answer."),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        default_model="test-model",
    )

    service.run(AgentServiceRequest(message="Just chat."))
    service.run(AgentServiceRequest(
        message="Generate an image.",
        image_generation={"enabled": True, "size": "1024x1024", "quality": "medium", "format": "png"},
    ))

    first_tools = [tool.get("function", {}).get("name") for tool in provider.requests[0].tools]
    second_tools = [tool.get("function", {}).get("name") for tool in provider.requests[1].tools]
    assert CREATE_IMAGE_ARTIFACT_TOOL not in first_tools
    assert CREATE_IMAGE_ARTIFACT_TOOL in second_tools
    assert not any(tool.get("type") == "image_generation" for tool in provider.requests[1].tools)
    assert provider.requests[1].request_options["_paper_notes_image_generation"]["quality"] == "medium"
    assert "create a downloadable image" in provider.requests[1].instructions


def test_service_generated_image_tool_artifact_is_returned_and_persisted(tmp_path):
    provider = FakeProvider([
        ModelResponse(
            content="",
            tool_calls=[ToolCall(
                id="call_image",
                name=CREATE_IMAGE_ARTIFACT_TOOL,
                arguments=json.dumps({"prompt": "Draw a tiny square."}),
            )],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Created the image."),
    ])
    registry = ToolRegistry()
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    media_store = MediaStore(tmp_path / ".paper-notes" / "media")
    artifact = media_store.create_generated_image(PNG_DATA_URL, session_id="session-1", provider="fake", model="test-model")
    registry.register(ToolDefinition(
        name=CREATE_IMAGE_ARTIFACT_TOOL,
        description="Create image.",
        parameters={"type": "object", "properties": {"prompt": {"type": "string"}}},
        handler=lambda args: {
            "success": True,
            "changed": True,
            "summary": "Generated image.",
            "artifact": artifact.to_dict(),
            "artifacts": [artifact.to_dict()],
        },
        result_max_chars=4000,
    ))
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=registry,
        media_store=media_store,
        default_model="test-model",
    )

    result = service.run(AgentServiceRequest(
        message="Generate an image.",
        image_generation={"enabled": True, "size": "1024x1024", "quality": "medium", "format": "png"},
    ))

    assert result.completed is True
    assert len(result.artifacts) == 1
    assert result.artifacts[0]["kind"] == "image"
    persisted = store.require_session(result.session_id).messages
    assert persisted[-1]["artifacts"][0]["id"] == artifact.id


def test_service_persists_request_provider_on_session(tmp_path):
    provider = FakeProvider([ModelResponse(content="A short answer.")])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )

    result = service.run(AgentServiceRequest(message="Summarize this.", provider="openai", model="gpt-5.5"))

    assert result.session.metadata.provider == "openai"
    assert result.session.metadata.model == "gpt-5.5"
    assert store.require_session(result.session_id).metadata.provider == "openai"


def test_service_reports_context_status_without_model_call(tmp_path):
    provider = FakeProvider([])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Long chat", provider="openai", model="gpt-5.5")
    store.append_message(session.metadata.session_id, {"role": "user", "content": "hello " * 20})
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Lookup a local fact.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: "ok",
    ))
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=registry,
    )

    status = service.context_status_fuc(session_id=session.metadata.session_id)

    assert status.provider == "openai"
    assert status.model == "gpt-5.5"
    assert status.context_length == 1_050_000
    assert status.message_count == 1
    assert status.actual_usage_available is False
    assert status.display_tokens == status.estimated_request_tokens
    assert status.request_tokens == status.estimated_request_tokens
    assert status.estimated_request_tokens > 0
    assert status.message_tokens > 0
    assert status.tool_schema_tokens > 0
    assert provider.requests == []


def test_service_reports_zero_used_tokens_for_empty_context(tmp_path):
    provider = FakeProvider([])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Empty chat", provider="openai", model="gpt-5.5")
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Lookup a local fact.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: "ok",
    ))
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=registry,
    )

    status = service.context_status_fuc(session_id=session.metadata.session_id)

    assert status.message_count == 0
    assert status.actual_usage_available is False
    assert status.display_tokens == 0
    assert status.request_tokens == status.estimated_request_tokens
    assert status.estimated_request_tokens > 0
    assert status.message_tokens == 0
    assert status.instruction_tokens > 0
    assert status.tool_schema_tokens > 0
    assert status.percent_full == 0
    assert provider.requests == []


def test_service_context_status_uses_last_actual_request_usage(tmp_path):
    provider = FakeProvider([
        ModelResponse(
            content="Done.",
            usage=TokenUsage(input_tokens=321, output_tokens=45, total_tokens=366),
        )
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="gpt-5.5",
    )

    result = service.run(AgentServiceRequest(message="Measure real usage.", title="Usage chat"))
    status = service.context_status_fuc(session_id=result.session_id)

    assert status.actual_usage_available is True
    assert status.actual_input_tokens == 321
    assert status.display_tokens == 321
    assert status.request_tokens == status.estimated_request_tokens
    assert status.message_tokens > 0
    assert status.instruction_tokens > 0
    assert status.tool_schema_tokens >= 0
    stored_usage = store.require_session(result.session_id).metadata.metadata["lastActualContextUsage"]
    assert stored_usage["inputTokens"] == 321
    assert "." in stored_usage["updatedAt"]


def test_service_context_status_falls_back_when_actual_usage_transcript_changes(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="First.", usage=TokenUsage(input_tokens=111, output_tokens=11, total_tokens=122)),
        ModelResponse(content="Second.", usage=TokenUsage(input_tokens=222, output_tokens=22, total_tokens=244)),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="gpt-5.5",
    )

    first = service.run(AgentServiceRequest(message="First prompt.", title="Usage chat"))
    service.run(AgentServiceRequest(message="Second prompt.", session_id=first.session_id))
    store.undo_last_turn(first.session_id)

    status = service.context_status_fuc(session_id=first.session_id)

    assert status.actual_usage_available is True
    assert status.actual_input_tokens == 111
    assert status.display_tokens == 111
    assert status.request_tokens == status.estimated_request_tokens


def test_manual_compaction_status_ignores_pre_compaction_actual_usage(tmp_path):
    provider = FakeProvider([])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Compact usage", provider="fake", model="test-model")
    for message in [
        {"role": "user", "content": "First question."},
        {"role": "assistant", "content": "Old answer " + ("x" * 240)},
        {"role": "user", "content": "Old followup " + ("y" * 240)},
        {"role": "assistant", "content": "Older answer " + ("z" * 240)},
        {"role": "user", "content": "Latest task should stay active."},
    ]:
        store.append_message(session.metadata.session_id, message)
    message_count = len(store.require_session(session.metadata.session_id).messages)
    store.update_session_metadata(session.metadata.session_id, {
        "lastActualContextUsage": {
            "inputTokens": 999_999,
            "outputTokens": 10,
            "totalTokens": 1_000_009,
            "provider": "fake",
            "model": "test-model",
            "transcriptMessageCount": message_count,
            "updatedAt": "2000-01-01T00:00:00+00:00",
        },
    })
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        context_compressor=hermes_test_compressor(ContextCompressionConfig(
            min_messages=3,
            protect_first_n=1,
            protect_last_n=1,
            tail_token_budget=16,
        )),
        default_model="test-model",
    )

    result = service.compact_session(session_id=session.metadata.session_id)

    assert result.compressed is True
    assert result.context.actual_usage_available is False
    assert result.context.request_tokens == result.context.estimated_request_tokens
    assert result.context.display_tokens == result.context.estimated_request_tokens
    assert result.context.display_tokens < 999_999
    metadata = store.require_session(session.metadata.session_id).metadata.metadata
    assert "lastActualContextUsage" not in metadata
    assert "." in metadata["lastActualContextUsageClearedAt"]
    checkpoint = service.compression_checkpoint_store.load(session.metadata.session_id)
    assert checkpoint is not None
    assert "." in checkpoint.updated_at


def test_service_context_status_falls_back_to_persisted_run_trace_usage(tmp_path):
    provider = FakeProvider([])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Replay chat", provider="codex-oauth", model="gpt-5.3-codex-spark")
    store.append_message(session.metadata.session_id, {"role": "user", "content": "hello"})
    store.append_message(session.metadata.session_id, {
        "role": "assistant",
        "content": "hi",
        "codex_reasoning_items": [{"encrypted_content": "x" * 8000}],
        "codex_message_items": [{"content": [{"text": "y" * 8000}]}],
        "provider_data": {"raw": "z" * 8000},
        "runTrace": {
            "requestId": "req_123",
            "finishedAt": "2026-05-16T10:00:00+00:00",
            "events": [{
                "type": "model_response",
                "data": {"input_tokens": 123, "output_tokens": 7, "total_tokens": 130},
            }],
        },
    })
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
    )

    status = service.context_status_fuc(session_id=session.metadata.session_id)

    assert status.message_count == 2
    assert status.actual_usage_available is True
    assert status.actual_input_tokens == 123
    assert status.display_tokens == 123
    assert status.request_tokens == status.estimated_request_tokens
    assert status.usage_request_id == "req_123"


def test_service_context_status_persists_latest_input_usage_from_tool_loop(tmp_path):
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="call_1", name="lookup", arguments='{"query": "paper"}')],
            finish_reason="tool_calls",
            usage=TokenUsage(input_tokens=100, output_tokens=20, total_tokens=120),
        ),
        ModelResponse(
            content="Done.",
            usage=TokenUsage(input_tokens=140, output_tokens=30, total_tokens=170),
        ),
    ])
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Lookup.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=lambda args: {"ok": True},
    ))
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=registry,
        default_model="test-model",
    )

    result = service.run(AgentServiceRequest(message="Use lookup.", title="Usage loop"))
    status = service.context_status_fuc(session_id=result.session_id)
    stored_usage = store.require_session(result.session_id).metadata.metadata["lastActualContextUsage"]

    assert status.actual_usage_available is True
    assert status.actual_input_tokens == 140
    assert status.display_tokens == 140
    assert status.request_tokens == status.estimated_request_tokens
    assert stored_usage["inputTokens"] == 140
    assert stored_usage["totalTokens"] == 170


def test_service_context_status_does_not_estimate_from_attachment_text(tmp_path):
    provider = FakeProvider([])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
    )
    session = store.create_session(title="Attachment chat", provider="openai", model="gpt-5.5")
    attachment_text = "alpha " * 200
    artifact = service.media_store.create_upload(
        "data:text/plain;base64," + base64.b64encode(attachment_text.encode("utf-8")).decode("ascii"),
        file_name="notes.txt",
        scope="session-1",
    )
    store.append_message(session.metadata.session_id, {
        "role": "user",
        "content": "Please read the attachment.",
        "attachments": [artifact.to_dict()],
    })

    status = service.context_status_fuc(session_id=session.metadata.session_id)

    assert status.message_count == 1
    assert status.actual_usage_available is False
    assert status.display_tokens == status.estimated_request_tokens
    assert status.estimated_request_tokens > 0
    assert status.message_tokens > 0
    assert status.request_tokens == status.estimated_request_tokens


def test_service_preserves_prior_run_traces_across_non_compressed_turns(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="Second answer.", usage=TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30)),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Trace chat", provider="codex-oauth", model="gpt-5.3-codex-spark")
    store.append_message(session.metadata.session_id, {"role": "user", "content": "First"})
    store.append_message(session.metadata.session_id, {
        "role": "assistant",
        "content": "First answer.",
        "runTrace": {
            "requestId": "req_first",
            "finishedAt": "2026-05-16T10:00:00+00:00",
            "events": [{
                "type": "model_response",
                "data": {"input_tokens": 11, "output_tokens": 12, "total_tokens": 23},
            }],
        },
    })
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        default_model="gpt-5.3-codex-spark",
    )

    result = service.run(AgentServiceRequest(
        message="Second",
        session_id=session.metadata.session_id,
        provider="codex-oauth",
        model="gpt-5.3-codex-spark",
    ))
    persisted = store.require_session(result.session_id).messages
    status = service.context_status_fuc(session_id=result.session_id)

    assert persisted[1]["runTrace"]["requestId"] == "req_first"
    assert persisted[-1]["runTrace"]["events"][1]["data"]["total_tokens"] == 30
    assert status.actual_input_tokens == 20
    assert status.display_tokens == 20


def test_service_preserves_prior_run_traces_across_compressed_turns(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="Fresh answer.", usage=TokenUsage(input_tokens=40, output_tokens=20, total_tokens=60)),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Compressed trace chat", provider="codex-oauth", model="gpt-5.3-codex-spark")
    store.append_message(session.metadata.session_id, {"role": "user", "content": "First " + ("x" * 240)})
    store.append_message(session.metadata.session_id, {
        "role": "assistant",
        "content": "First answer. " + ("y" * 240),
        "runTrace": {
            "requestId": "req_first",
            "finishedAt": "2026-05-16T10:00:00+00:00",
            "events": [{
                "type": "model_response",
                "data": {"input_tokens": 11, "output_tokens": 12, "total_tokens": 23},
            }],
        },
    })
    store.append_message(session.metadata.session_id, {"role": "user", "content": "Older " + ("z" * 240)})
    store.append_message(session.metadata.session_id, {"role": "assistant", "content": "Older answer. " + ("w" * 240)})
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        context_compressor=hermes_test_compressor(ContextCompressionConfig(
            max_estimated_tokens=1,
            min_messages=4,
            protect_first_n=1,
            protect_last_n=2,
            tail_token_budget=16,
        )),
        default_model="gpt-5.3-codex-spark",
    )

    result = service.run(AgentServiceRequest(
        message="Second task",
        session_id=session.metadata.session_id,
        provider="codex-oauth",
        model="gpt-5.3-codex-spark",
    ))
    persisted = store.require_session(result.session_id).messages
    status = service.context_status_fuc(session_id=result.session_id)

    assert persisted[1]["runTrace"]["requestId"] == "req_first"
    assert isinstance(persisted[-1].get("runTrace"), dict)
    assert status.actual_input_tokens == 40
    assert status.display_tokens == 40


def test_service_context_status_uses_last_model_response_input_tokens_per_turn(tmp_path):
    provider = FakeProvider([])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Tool loop chat", provider="codex-oauth", model="gpt-5.3-codex-spark")
    store.append_message(session.metadata.session_id, {"role": "user", "content": "Do the task"})
    store.append_message(session.metadata.session_id, {
        "role": "assistant",
        "content": "Done.",
        "runTrace": {
            "requestId": "req_tool_loop",
            "finishedAt": "2026-05-16T10:00:00+00:00",
            "events": [
                {"type": "model_request", "data": {"turn": 1}},
                {"type": "model_response", "data": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}},
                {"type": "tool_call", "data": {"name": "lookup"}},
                {"type": "model_request", "data": {"turn": 2}},
                {"type": "model_response", "data": {"input_tokens": 140, "output_tokens": 30, "total_tokens": 170}},
            ],
        },
    })
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
    )

    status = service.context_status_fuc(session_id=session.metadata.session_id)

    assert status.actual_input_tokens == 140
    assert status.display_tokens == 140


def test_service_reuses_existing_session_history(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="First answer."),
        ModelResponse(content="Second answer."),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(model_provider=provider, session_store=store, tool_registry=ToolRegistry())

    first = service.run(AgentServiceRequest(message="First", model="test-model"))
    second = service.run(AgentServiceRequest(message="Second", session_id=first.session_id, model="test-model"))

    assert second.created_session is False
    assert [message["role"] for message in provider.requests[1].messages] == ["system", "user", "assistant", "user"]
    assert "# Runtime context" in provider.requests[1].messages[0]["content"]
    assert provider.requests[1].messages[-1]["content"] == "Second"
    assert [message["content"] for message in second.messages] == [
        "First",
        "First answer.",
        "Second",
        "Second answer.",
    ]


def test_service_compresses_model_visible_context_without_replacing_transcript(tmp_path):
    provider = FakeProvider([ModelResponse(content="Fresh answer.")])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Long chat", model="test-model")
    for index in range(8):
        store.append_message(session.metadata.session_id, {
            "role": "user",
            "content": f"old user {index} " + ("x" * 240),
        })
        store.append_message(session.metadata.session_id, {
            "role": "assistant",
            "content": f"old assistant {index} " + ("y" * 240),
        })
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        context_compressor=hermes_test_compressor(ContextCompressionConfig(
            max_estimated_tokens=1,
            min_messages=4,
            protect_first_n=1,
            protect_last_n=2,
            tail_token_budget=16,
        )),
    )
    events = []

    result = service.run(AgentServiceRequest(
        message="latest task",
        session_id=session.metadata.session_id,
        model="test-model",
        event_sink=events.append,
    ))

    model_messages = provider.requests[0].messages
    assert any(str(message.get("content", "")).startswith(SUMMARY_PREFIX) for message in model_messages)
    assert [event.type for event in events[:2]] == ["context_compressing", "context_compressed"]
    assert [event.type for event in result.events[:2]] == ["context_compressing", "context_compressed"]
    persisted = store.require_session(session.metadata.session_id).messages
    checkpoint = service.compression_checkpoint_store.load(session.metadata.session_id)
    assert checkpoint is not None
    assert checkpoint.summary_available is True
    assert checkpoint.compressed_until_message_index > 0
    assert service.compression_checkpoint_store.path_for(session.metadata.session_id).parent == (
        tmp_path / ".paper-notes" / "compression"
    )
    assert persisted[0]["content"].startswith("old user 0")
    assert not any(str(message.get("content", "")).startswith(SUMMARY_PREFIX) for message in persisted)
    assert persisted[-2]["content"] == "latest task"
    assert persisted[-1]["content"] == "Fresh answer."


def test_service_preflight_compression_includes_tool_schema_tokens(tmp_path):
    provider = FakeProvider([ModelResponse(content="Fresh answer.")])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Tool-heavy chat", model="test-model")
    for index in range(4):
        store.append_message(session.metadata.session_id, {"role": "user", "content": f"old user {index}"})
        store.append_message(session.metadata.session_id, {"role": "assistant", "content": f"old answer {index}"})
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="big_tool",
        description="x" * 10_000,
        parameters={"type": "object", "properties": {}},
        handler=lambda args: "ok",
    ))
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=registry,
        context_compressor=hermes_test_compressor(ContextCompressionConfig(
            max_estimated_tokens=500,
            min_messages=4,
            protect_first_n=1,
            protect_last_n=2,
            tail_token_budget=16,
        )),
    )

    result = service.run(AgentServiceRequest(
        message="latest task",
        session_id=session.metadata.session_id,
        model="test-model",
    ))

    assert result.completed is True
    assert any(event.type == "context_compressed" for event in result.events)
    assert any(str(message.get("content", "")).startswith(SUMMARY_PREFIX) for message in provider.requests[0].messages)


def test_service_retries_context_overflow_with_forced_compression(tmp_path):
    provider = OverflowThenSuccessProvider()
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Overflow chat", model="test-model")
    for index in range(8):
        store.append_message(session.metadata.session_id, {
            "role": "user",
            "content": f"old user {index} " + ("x" * 240),
        })
        store.append_message(session.metadata.session_id, {
            "role": "assistant",
            "content": f"old assistant {index} " + ("y" * 240),
        })
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        context_compressor=hermes_test_compressor(ContextCompressionConfig(
            max_estimated_tokens=999_999,
            min_messages=4,
            protect_first_n=1,
            protect_last_n=2,
            tail_token_budget=16,
        )),
    )
    events = []

    result = service.run(AgentServiceRequest(
        message="latest task",
        session_id=session.metadata.session_id,
        model="test-model",
        event_sink=events.append,
    ))

    assert result.completed is True
    assert len(provider.requests) == 2
    assert not any(str(message.get("content", "")).startswith(SUMMARY_PREFIX) for message in provider.requests[0].messages)
    assert any(str(message.get("content", "")).startswith(SUMMARY_PREFIX) for message in provider.requests[1].messages)
    assert [event.type for event in events].count("context_overflow") == 1
    assert any(event.type == "context_compressed" and event.data["reason"] == "context_overflow" for event in result.events)
    persisted = store.require_session(session.metadata.session_id).messages
    assert not any(str(message.get("content", "")).startswith(SUMMARY_PREFIX) for message in persisted)
    assert persisted[-1]["content"] == "Recovered after compression."


def test_service_reuses_persisted_compression_checkpoint_on_next_turn(tmp_path):
    provider = FakeProvider([
        ModelResponse(content="First fresh answer."),
        ModelResponse(content="Second fresh answer."),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Long chat", model="test-model")
    for index in range(8):
        store.append_message(session.metadata.session_id, {
            "role": "user",
            "content": f"old user {index} " + ("x" * 240),
        })
        store.append_message(session.metadata.session_id, {
            "role": "assistant",
            "content": f"old assistant {index} " + ("y" * 240),
        })
    compressor = hermes_test_compressor(ContextCompressionConfig(
        max_estimated_tokens=1,
        min_messages=4,
        protect_first_n=1,
        protect_last_n=2,
        tail_token_budget=16,
    ))
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        context_compressor=compressor,
    )

    first = service.run(AgentServiceRequest(
        message="latest task",
        session_id=session.metadata.session_id,
        model="test-model",
    ))
    assert any(event.type == "context_compressed" for event in first.events)
    checkpoint = service.compression_checkpoint_store.load(session.metadata.session_id)
    assert checkpoint is not None
    assert checkpoint.summary_available is True

    compressor.config.max_estimated_tokens = 999_999
    second = service.run(AgentServiceRequest(
        message="follow-up after checkpoint",
        session_id=session.metadata.session_id,
        model="test-model",
    ))

    assert second.completed is True
    assert any(str(message.get("content", "")).startswith(SUMMARY_PREFIX) for message in provider.requests[-1].messages)
    persisted = store.require_session(session.metadata.session_id).messages
    assert persisted[-2]["content"] == "follow-up after checkpoint"
    assert persisted[-1]["content"] == "Second fresh answer."


def test_service_can_manually_compact_session_and_adds_transcript_marker(tmp_path):
    provider = FakeProvider([])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Manual compact", model="test-model")
    for index in range(8):
        store.append_message(session.metadata.session_id, {
            "role": "user",
            "content": f"old user {index} " + ("x" * 240),
        })
        store.append_message(session.metadata.session_id, {
            "role": "assistant",
            "content": f"old assistant {index} " + ("y" * 240),
        })
    service = AgentService(
        model_provider=provider,
        session_store=store,
        tool_registry=ToolRegistry(),
        context_compressor=hermes_test_compressor(ContextCompressionConfig(
            max_estimated_tokens=999_999,
            min_messages=4,
            protect_first_n=1,
            protect_last_n=2,
            tail_token_budget=16,
        )),
    )

    result = service.compact_session(
        session_id=session.metadata.session_id,
        focus="implementation plan",
        model="test-model",
    )

    assert result.compressed is True
    assert result.context.summary_available is True
    assert result.context.compression_count == 1
    assert [event.type for event in result.events][:2] == ["context_compressing", "context_compressed"]
    checkpoint = service.compression_checkpoint_store.load(session.metadata.session_id)
    assert checkpoint is not None
    assert checkpoint.current_summary
    persisted = store.require_session(session.metadata.session_id).messages
    assert len(persisted) == 17
    assert persisted[-1]["role"] == "divider"
    assert persisted[-1]["metadata"]["type"] == "context_compaction_marker"
    assert "Context compacted" in persisted[-1]["content"]
    assert not any(str(message.get("content", "")).startswith(SUMMARY_PREFIX) for message in persisted)


def test_service_exposes_tools_executes_tool_loop_and_persists_messages(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Lookup a local fact.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=lambda args: {"answer": f"found {args['query']}"},
        toolset="test",
    ))
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="call_1", name="lookup", arguments='{"query": "rag"}')],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Found it.", finish_reason="stop"),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(model_provider=provider, session_store=store, tool_registry=registry)

    result = service.run(AgentServiceRequest(message="Find RAG", model="test-model"))

    assert result.completed is True
    assert provider.requests[0].tools[0]["function"]["name"] == "lookup"
    assert [message["role"] for message in result.messages] == ["user", "assistant", "tool", "assistant"]
    tool_payload = json.loads(result.messages[2]["content"])
    assert tool_payload == {"answer": "found rag"}


def test_service_default_toolsets_expose_session_todo_and_inject_active_items(tmp_path):
    todo_arguments = json.dumps({
        "todos": [
            {"id": "1", "content": "Read the introduction", "status": "in_progress"},
            {"id": "2", "content": "Compare annotations", "status": "pending"},
        ],
    })
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="todo_call_1", name="todo", arguments=todo_arguments)],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Plan saved.", finish_reason="stop"),
        ModelResponse(content="Continuing from the plan.", finish_reason="stop"),
    ])
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    service = AgentService(
        model_provider=provider,
        session_store=store,
        memory_path=tmp_path / ".paper-notes" / "memory",
    )

    first = service.run(AgentServiceRequest(message="Plan this reading task.", model="test-model"))
    second = service.run(AgentServiceRequest(
        message="Continue.",
        session_id=first.session_id,
        model="test-model",
    ))

    first_tool_names = {tool["function"]["name"] for tool in provider.requests[0].tools}
    assert {
            "search_notes",
            "get_note_context",
            "read_paper",
            "review_note",
        "persistent_memory",
        "session_search",
        "todo",
        "skills_list",
        "skill_view",
        "execute_code",
    } <= first_tool_names
    todo_payload = json.loads(first.messages[2]["content"])
    assert todo_payload["summary"] == {
        "total": 2,
        "pending": 1,
        "in_progress": 1,
        "completed": 0,
        "cancelled": 0,
    }
    metadata = store.require_session(first.session_id).metadata.metadata
    assert metadata[TODO_METADATA_KEY][0]["content"] == "Read the introduction"
    assert "<todo-context>" in provider.requests[-1].instructions
    assert "Read the introduction" in provider.requests[-1].instructions
    assert "Compare annotations" in provider.requests[-1].instructions
    assert second.response == "Continuing from the plan."


def test_service_exposes_executes_and_persists_skill_tools(tmp_path):
    skill_dir = tmp_path / ".paper-notes" / "skills" / "paper-skim"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: paper-skim\ndescription: Skim paper claims.\n---\n\nUse Paper Notes context carefully.",
        encoding="utf-8",
    )
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(
                id="skill_call_1",
                name="skill_view",
                arguments=json.dumps({"name": "paper-skim"}),
            )],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Skill loaded.", finish_reason="stop"),
        ModelResponse(content="Continuing with skill context.", finish_reason="stop"),
    ])
    registry = create_paper_notes_registry()
    register_skills_tools(registry, store=SkillStore([tmp_path / ".paper-notes" / "skills"]))
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        use_memory=False,
        use_session_search=False,
        use_compression=False,
    )

    first = service.run(AgentServiceRequest(message="Use the paper-skim skill.", model="test-model"))
    second = service.run(AgentServiceRequest(message="Continue.", session_id=first.session_id, model="test-model"))

    first_tool_names = {tool["function"]["name"] for tool in provider.requests[0].tools}
    second_contents = [str(message.get("content") or "") for message in provider.requests[-1].messages]
    tool_payload = json.loads(first.messages[2]["content"])

    assert "skill_view" in first_tool_names
    assert "skills_list" in first_tool_names
    assert tool_payload["success"] is True
    assert tool_payload["name"] == "paper-skim"
    assert "Use Paper Notes context carefully" in tool_payload["content"]
    assert any("paper-skim" in content and "Use Paper Notes context carefully" in content for content in second_contents)
    assert second.response == "Continuing with skill context."


def test_todo_tool_rejects_empty_content_and_multiple_in_progress(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session(title="Todo")
    todo_store = SessionTodoStore(store, current_session_id_provider=lambda: session.metadata.session_id)
    tool = create_todo_tool_definition(todo_store)

    empty = tool.handler({"todos": [{"id": "1", "content": "", "status": "pending"}]})
    multiple = tool.handler({
        "todos": [
            {"id": "1", "content": "First", "status": "in_progress"},
            {"id": "2", "content": "Second", "status": "in_progress"},
        ],
    })

    assert empty["success"] is False
    assert "content is required" in empty["error"]
    assert multiple["success"] is False
    assert "at most one in_progress" in multiple["error"]
    assert store.require_session(session.metadata.session_id).metadata.metadata.get(TODO_METADATA_KEY) is None


def test_service_can_disable_todo_toolset_for_default_tools(tmp_path):
    provider = FakeProvider([ModelResponse(content="No todo available.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        memory_path=tmp_path / ".paper-notes" / "memory",
    )

    service.run(AgentServiceRequest(
        message="Hello",
        model="test-model",
        disabled_toolsets=["todo"],
    ))

    tool_names = {tool["function"]["name"] for tool in provider.requests[0].tools}
    assert "todo" not in tool_names
    assert "search_notes" in tool_names


def test_service_can_disable_paper_notes_write_tools_for_default_tools(tmp_path):
    provider = FakeProvider([ModelResponse(content="Readonly only.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        memory_path=tmp_path / ".paper-notes" / "memory",
    )

    service.run(AgentServiceRequest(
        message="Hello",
        model="test-model",
        enabled_toolsets=["readonly", "persistent_memory", "todo"],
    ))

    tool_names = {tool["function"]["name"] for tool in provider.requests[0].tools}
    assert "search_notes" in tool_names
    assert "get_note_context" in tool_names
    assert "read_paper" in tool_names
    assert "review_note" in tool_names
    assert "session_search" in tool_names
    assert "write_note" not in tool_names
    assert "manage_annotations" not in tool_names
    assert "write_note_media" not in tool_names


def test_service_execute_code_description_lists_visible_readonly_tools_only(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="search_notes",
        description="Search.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="paper_notes",
        read_only=True,
        risk="read",
    ))
    registry.register(ToolDefinition(
        name="get_note_context",
        description="Context.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="paper_notes",
        read_only=True,
        risk="read",
    ))
    registry.register(ToolDefinition(
        name="write_note",
        description="Edit.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="paper_notes",
        mutating=True,
        risk="write",
    ))
    registry.register(ToolDefinition(
        name="web_search",
        description="Search web.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="web_search",
        read_only=True,
        risk="read",
        kind="search",
    ))
    register_code_execution_tool(registry)
    provider = FakeProvider([ModelResponse(content="Schema checked.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        use_memory=False,
        use_session_search=False,
        use_compression=False,
    )

    service.run(AgentServiceRequest(
        message="Hello",
        model="test-model",
        enabled_toolsets=["code_execution", "paper_notes"],
    ))

    execute_code_tool = next(
        tool for tool in provider.requests[0].tools
        if tool["function"]["name"] == "execute_code"
    )
    description = execute_code_tool["function"]["description"]
    assert "search_notes" in description
    assert "write_note" not in description
    assert "web_search" not in description


def test_service_execute_code_uses_existing_approval_modes(tmp_path):
    registry = ToolRegistry()
    register_code_execution_tool(registry)
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(
                id="code_call_1",
                name="execute_code",
                arguments=json.dumps({"code": "print('approved')"}),
            )],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Done.", finish_reason="stop"),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        use_memory=False,
        use_session_search=False,
        use_compression=False,
        tool_approval_manager=ToolApprovalManager(tmp_path / ".paper-notes" / "approvals"),
    )
    session = service.session_store.create_session(title="Code Approval")
    holder: dict[str, object] = {}

    def run_service() -> None:
        holder["result"] = service.run(AgentServiceRequest(
            message="Run code.",
            session_id=session.metadata.session_id,
            model="test-model",
            write_tool_mode="ask",
        ))

    thread = threading.Thread(target=run_service)
    thread.start()
    approval = _wait_for_pending_approval(service, session.metadata.session_id)
    service.respond_tool_approval(approval_id=approval["approvalId"], action="allow_once")
    thread.join(timeout=5)

    assert not thread.is_alive()
    result = holder["result"]
    tool_payload = json.loads(result.messages[2]["content"])
    assert result.completed is True
    assert tool_payload["success"] is True
    assert tool_payload["output"] == "approved\n"


def test_service_execute_code_auto_mode_runs_without_approval(tmp_path):
    registry = ToolRegistry()
    register_code_execution_tool(registry)
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(
                id="code_call_1",
                name="execute_code",
                arguments=json.dumps({"code": "print('auto')"}),
            )],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Done.", finish_reason="stop"),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        use_memory=False,
        use_session_search=False,
        use_compression=False,
        tool_approval_manager=ToolApprovalManager(tmp_path / ".paper-notes" / "approvals"),
    )

    result = service.run(AgentServiceRequest(message="Run code.", model="test-model", write_tool_mode="auto"))

    tool_payload = json.loads(result.messages[2]["content"])
    assert result.completed is True
    assert tool_payload["success"] is True
    assert tool_payload["output"] == "auto\n"
    assert not any(event.type == "tool_approval_requested" for event in result.events)


def test_service_execute_code_cannot_inner_write_paper_note(tmp_path):
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
    snapshot_manager = PaperNotesSnapshotManager(
        tmp_path / ".paper-notes" / "snapshots",
        project_root=tmp_path,
        notes_path=library_path,
        html_dir=html_dir,
        annotations_dir=annotations_dir,
    )
    registry = create_paper_notes_registry(library_path=library_path, html_dir=html_dir)
    session_id_holder = {"session_id": ""}
    register_code_execution_tool(
        registry,
        available_tool_names_provider=lambda: ("execute_code", "write_note"),
        snapshot_manager_provider=lambda: snapshot_manager,
        session_id_provider=lambda: session_id_holder["session_id"],
    )
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(
                id="code_call_write",
                name="execute_code",
                arguments=json.dumps({
                    "code": (
                        "from paper_notes_tools import write_note\n"
                        "write_note('append_to_section', 'note-1', heading='From Code', html='<p>temporary</p>')\n"
                    ),
                }),
            )],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Done.", finish_reason="stop"),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        use_memory=False,
        use_session_search=False,
        use_compression=False,
        tool_snapshot_manager=snapshot_manager,
    )
    session = service.session_store.create_session(title="Code Snapshot")
    session_id_holder["session_id"] = session.metadata.session_id

    result = service.run(AgentServiceRequest(
        message="Run code.",
        session_id=session.metadata.session_id,
        model="test-model",
        write_tool_mode="auto",
        enabled_toolsets=["code_execution", "paper_notes"],
    ))

    tool_payload = json.loads(result.messages[2]["content"])
    persisted = service.session_store.require_session(result.session_id)
    assert tool_payload["success"] is False
    assert tool_payload.get("snapshot") is None
    assert persisted.messages[-1].get("toolActivity", []) == []
    assert "write_note" in tool_payload["error"]
    assert "From Code" not in html_path.read_text(encoding="utf-8")


def test_service_can_execute_paper_note_write_tool(tmp_path):
    library_path = tmp_path / "notes.json"
    html_dir = tmp_path / "Paper-html"
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
    registry = create_paper_notes_registry(library_path=library_path, html_dir=html_dir)
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(
                id="call_1",
                name="write_note",
                arguments=json.dumps({
                    "action": "append_to_section",
                    "note_id": "note-1",
                    "heading": "Agent Notes",
                    "html": "<p>Written by the agent.</p>",
                }),
            )],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Updated the note.", finish_reason="stop"),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        tool_snapshot_manager=PaperNotesSnapshotManager(
            tmp_path / ".paper-notes" / "snapshots",
            project_root=tmp_path,
            notes_path=library_path,
            html_dir=html_dir,
            annotations_dir=tmp_path / "Paper-annotations",
        ),
    )

    result = service.run(AgentServiceRequest(message="Write this into the note.", model="test-model"))

    assert result.completed is True
    tool_payload = json.loads(result.messages[2]["content"])
    assert tool_payload["success"] is True
    persisted = service.session_store.require_session(result.session_id)
    assert persisted.messages[-1]["toolActivity"][0]["name"] == "write_note"
    assert persisted.messages[-1]["toolActivity"][0]["changedFiles"][0]["path"] == "Paper-html/note-1.html"
    assert '<h2 id="agent-notes">Agent Notes</h2>' in html_path.read_text(encoding="utf-8")


def test_service_readonly_write_mode_hides_mutating_tools(tmp_path):
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

    service.run(AgentServiceRequest(message="Hello", model="test-model", write_tool_mode="readonly"))

    assert [tool["function"]["name"] for tool in provider.requests[0].tools] == ["read_tool"]


def test_service_disabled_tools_hide_specific_registered_tools(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="read_tool",
        description="Read.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="other_read_tool",
        description="Read too.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        read_only=True,
    ))
    provider = FakeProvider([ModelResponse(content="Filtered.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
    )

    service.run(AgentServiceRequest(
        message="Hello",
        model="test-model",
        disabled_tools=["other_read_tool"],
    ))

    assert [tool["function"]["name"] for tool in provider.requests[0].tools] == ["read_tool"]


def test_service_per_tool_readonly_mode_hides_that_mutating_tool(tmp_path):
    registry = ToolRegistry()
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

    service.run(AgentServiceRequest(
        message="Hello",
        model="test-model",
        tool_write_modes={"other_write_tool": "readonly"},
    ))

    assert [tool["function"]["name"] for tool in provider.requests[0].tools] == ["write_tool"]


def test_service_warn_write_mode_emits_mutating_tool_warning(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="write_tool",
        description="Write.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True, "changed": True},
        mutating=True,
        risk="write",
    ))
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="call_1", name="write_tool", arguments="{}")],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Done.", finish_reason="stop"),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
    )

    result = service.run(AgentServiceRequest(message="Write.", model="test-model", write_tool_mode="warn"))

    assert result.completed is True
    assert any(
        event.type == "tool_warning" and event.data.get("code") == "mutating_tool_warn_mode"
        for event in result.events
    )


def test_service_ask_write_mode_waits_for_approval_then_runs_tool(tmp_path):
    tool_calls: list[dict] = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="write_tool",
        description="Write.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: tool_calls.append(args) or {"success": True, "changed": True},
        mutating=True,
        risk="write",
    ))
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="call_approve", name="write_tool", arguments="{}")],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Done.", finish_reason="stop"),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        tool_approval_manager=ToolApprovalManager(tmp_path / ".paper-notes" / "approvals"),
    )
    session = service.session_store.create_session(title="Approval")
    holder: dict[str, object] = {}

    def run_service() -> None:
        holder["result"] = service.run(AgentServiceRequest(
            message="Write.",
            session_id=session.metadata.session_id,
            request_id="req-approval",
            model="test-model",
            write_tool_mode="ask",
        ))

    thread = threading.Thread(target=run_service)
    thread.start()
    approval = _wait_for_pending_approval(service, session.metadata.session_id)
    service.respond_tool_approval(approval_id=approval["approvalId"], action="allow_once")
    thread.join(timeout=2)

    assert not thread.is_alive()
    result = holder["result"]
    assert result.completed is True
    assert tool_calls == [{}]
    event_types = [event.type for event in result.events]
    assert "tool_approval_requested" in event_types
    assert "tool_approval_resolved" in event_types


def test_service_ask_write_mode_denies_tool_without_running_handler(tmp_path):
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
            tool_calls=[ToolCall(id="call_deny", name="write_tool", arguments="{}")],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Did not write.", finish_reason="stop"),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        tool_approval_manager=ToolApprovalManager(tmp_path / ".paper-notes" / "approvals"),
    )
    session = service.session_store.create_session(title="Approval")
    holder: dict[str, object] = {}

    def run_service() -> None:
        holder["result"] = service.run(AgentServiceRequest(
            message="Write.",
            session_id=session.metadata.session_id,
            model="test-model",
            write_tool_mode="ask",
        ))

    thread = threading.Thread(target=run_service)
    thread.start()
    approval = _wait_for_pending_approval(service, session.metadata.session_id)
    service.respond_tool_approval(approval_id=approval["approvalId"], action="deny")
    thread.join(timeout=2)

    assert not thread.is_alive()
    result = holder["result"]
    assert result.completed is True
    assert tool_calls == []
    tool_payload = json.loads(result.messages[2]["content"])
    assert tool_payload["code"] == "tool_approval_denied"


def test_service_can_restore_mutating_tool_snapshot(tmp_path):
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
    registry = create_paper_notes_registry(library_path=library_path, html_dir=html_dir)
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(
                id="call_restore",
                name="write_note",
                arguments=json.dumps({
                    "action": "append_to_section",
                    "note_id": "note-1",
                    "heading": "Restore Me",
                    "html": "<p>Temporary.</p>",
                }),
            )],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="Updated.", finish_reason="stop"),
    ])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        tool_snapshot_manager=PaperNotesSnapshotManager(
            tmp_path / ".paper-notes" / "snapshots",
            project_root=tmp_path,
            notes_path=library_path,
            html_dir=html_dir,
            annotations_dir=annotations_dir,
        ),
    )

    result = service.run(AgentServiceRequest(message="Write temp section.", model="test-model"))
    snapshot = next(event.data["snapshot"] for event in result.events if event.type == "tool_result")
    assert "Restore Me" in html_path.read_text(encoding="utf-8")

    restored = service.restore_tool_snapshot(session_id=result.session_id, snapshot_id=snapshot["snapshotId"])

    assert restored["success"] is True
    assert "Restore Me" not in html_path.read_text(encoding="utf-8")


def test_service_can_disable_tools(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Lookup a local fact.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"answer": "found"},
    ))
    provider = FakeProvider([ModelResponse(content="No tools used.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
    )

    service.run(AgentServiceRequest(message="Hello", model="test-model", enable_tools=False))

    assert provider.requests[0].tools == []
    assert "Retrieval tools unavailable" in provider.requests[0].instructions
    assert "Do not claim that you searched" in provider.requests[0].instructions


def test_service_injects_prefetched_memory_into_prompt(tmp_path):
    memory_provider = LocalMemoryProvider(memory_path=tmp_path / "memory")
    memory_provider.store.add("I prefer concise summaries.", target=USER_TARGET)
    provider = FakeProvider([ModelResponse(content="Got it.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        memory_manager=MemoryManager([memory_provider]),
    )

    service.run(AgentServiceRequest(message="Can you be concise?", model="test-model"))

    assert "<memory-context>" in provider.requests[0].instructions
    assert "I prefer concise summaries" in provider.requests[0].instructions
    assert provider.requests[0].tools[0]["function"]["name"] == "persistent_memory"


def test_service_syncs_explicit_memory_after_successful_run(tmp_path):
    memory_provider = LocalMemoryProvider(memory_path=tmp_path / "memory")
    provider = FakeProvider([ModelResponse(content="I'll remember that.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        memory_manager=MemoryManager([memory_provider]),
    )

    service.run(AgentServiceRequest(message="Remember that I prefer concise summaries.", model="test-model"))

    memories = memory_provider.store.read(USER_TARGET)
    assert memories["entries"] == ["I prefer concise summaries"]


def test_service_missing_session_raises(tmp_path):
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )

    with pytest.raises(SessionNotFoundError):
        service.run(AgentServiceRequest(message="Hello", session_id="missing", model="test-model"))
